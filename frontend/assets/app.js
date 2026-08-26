const API = '/api';

let map;
let unitLayer;
let alcaldiaLayer;
let predictionMap;
let predictionMarker;
let selectedPredictionPoint = null;
let sectorChart;
let alcaldiaChart;
let alcaldiasGeoJSON = null;

const $ = (id) => document.getElementById(id);
const fmt = (value) => new Intl.NumberFormat('es-MX').format(Number(value) || 0);
const pct = (value) => `${Number(value || 0).toFixed(1)}%`;

async function api(path, options) {
  const res = await fetch(`${API}${path}`, options);
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

function initMaps() {
  map = L.map('map', { zoomControl: true, preferCanvas: true }).setView([19.4326, -99.1332], 10);
  predictionMap = L.map('prediction-map').setView([19.4326, -99.1332], 10);

  const tiles = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
  const attribution = '&copy; OpenStreetMap contributors';
  L.tileLayer(tiles, { attribution, maxZoom: 19 }).addTo(map);
  L.tileLayer(tiles, { attribution, maxZoom: 19 }).addTo(predictionMap);

  predictionMap.on('click', onPredictionClick);
}

async function bootstrap() {
  await checkHealth();

  try {
    const [alcaldias, sectores, actividades] = await Promise.all([
      api('/alcaldias'),
      api('/sectores'),
      api('/actividades'),
    ]);

    alcaldias.forEach((a) => {
      $('filter-alcaldia').insertAdjacentHTML('beforeend', `<option value="${a.id}">${escapeHtml(a.nombre)}</option>`);
    });

    sectores.forEach((s) => {
      $('filter-sector').insertAdjacentHTML('beforeend', `<option value="${s.id}">${escapeHtml(s.nombre)}</option>`);
    });

    renderActivityOptions(actividades);
    await loadAlcaldiasLayer();
    await loadDashboard();
  } catch (err) {
    console.error(err);
    renderDashboardError(err.message);
  }
}

async function checkHealth() {
  try {
    await api('/health');
    $('api-status').textContent = 'API conectada';
    $('api-dot').className = 'api-dot ok';
  } catch (err) {
    $('api-status').textContent = 'API sin conexión';
    $('api-dot').className = 'api-dot error';
  }
}

function renderActivityOptions(actividades) {
  const select = $('filter-actividad');
  const current = select.value;
  select.innerHTML = '<option value="">Todas las actividades</option>';
  actividades.forEach((a) => {
    select.insertAdjacentHTML(
      'beforeend',
      `<option value="${a.id}">${escapeHtml(a.codigo_scian)} · ${escapeHtml(a.descripcion)}</option>`
    );
  });
  if ([...select.options].some((o) => o.value === current)) select.value = current;
}

async function refreshActivitiesBySector() {
  const sectorId = $('filter-sector').value;
  const actividades = await api(`/actividades${sectorId ? `?sector_id=${sectorId}` : ''}`);
  renderActivityOptions(actividades);
}

function currentQuery() {
  const params = new URLSearchParams();
  if ($('filter-alcaldia').value) params.set('alcaldia_id', $('filter-alcaldia').value);
  if ($('filter-sector').value) params.set('sector_id', $('filter-sector').value);
  if ($('filter-actividad').value) params.set('actividad_id', $('filter-actividad').value);
  return params;
}

async function loadDashboard() {
  setDashboardLoading(true);
  try {
    const params = currentQuery();
    const summary = await api(`/dashboard/resumen?${params.toString()}`);

    renderSummary(summary);
    renderTopActivities(summary.top_actividades || []);
    renderSectorChart(summary.distribucion_sector || []);
    renderAlcaldiaChart(summary.distribucion_alcaldia || []);
    updateQueryTime(summary.consulta_generada);

    await Promise.all([loadUnits(), updateAlcaldiaLayerStyle()]);
  } catch (err) {
    console.error(err);
    renderDashboardError(err.message);
  } finally {
    setDashboardLoading(false);
  }
}

function renderSummary(summary) {
  $('summary-total').textContent = fmt(summary.total_unidades);
  $('summary-alcaldias').textContent = fmt(summary.alcaldias_representadas);

  const activity = summary.actividad_lider;
  $('summary-activity-code').textContent = activity ? activity.codigo_scian : '—';
  $('summary-activity-name').textContent = activity
    ? `${activity.descripcion} · ${fmt(activity.unidades)}`
    : 'Actividad económica líder';

  const sector = summary.sector_lider;
  $('summary-sector').textContent = sector ? sector.nombre : '—';
  $('summary-sector-count').textContent = sector
    ? `${fmt(sector.unidades)} unidades · ${pct(sector.porcentaje)}`
    : 'Sector predominante';
}

function renderTopActivities(items) {
  const tbody = $('top-activities-table');
  if (!items.length) {
    tbody.innerHTML = '<tr><td colspan="4" class="empty-cell">No hay registros para los filtros seleccionados.</td></tr>';
    return;
  }

  tbody.innerHTML = items.map((item) => `
    <tr>
      <td><span class="activity-code">${escapeHtml(item.codigo_scian)}</span></td>
      <td class="activity-name" title="${escapeHtml(item.descripcion)}">${escapeHtml(item.descripcion)}</td>
      <td class="numeric"><strong>${fmt(item.unidades)}</strong></td>
      <td class="numeric">${pct(item.porcentaje)}</td>
    </tr>
  `).join('');
}

function renderSectorChart(items) {
  if (sectorChart) sectorChart.destroy();

  const labels = items.map((i) => i.nombre);
  const values = items.map((i) => Number(i.unidades) || 0);
  const colors = ['#3155e7', '#27b881', '#f2a62b', '#6d4ce8'];

  sectorChart = new Chart($('sector-chart'), {
    type: 'doughnut',
    data: {
      labels,
      datasets: [{
        data: values,
        backgroundColor: colors.slice(0, Math.max(labels.length, 1)),
        borderWidth: 0,
        hoverOffset: 4,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: '66%',
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (ctx) => `${ctx.label}: ${fmt(ctx.raw)} unidades`,
          },
        },
      },
    },
    plugins: [centerTextPlugin(items)],
  });

  const legend = $('sector-legend');
  if (!items.length) {
    legend.innerHTML = '<p class="muted">Sin datos.</p>';
    return;
  }

  legend.innerHTML = items.map((item, index) => `
    <div class="legend-row">
      <span class="legend-swatch" style="background:${colors[index % colors.length]}"></span>
      <span>${escapeHtml(item.nombre)}</span>
      <strong>${pct(item.porcentaje)}</strong>
    </div>
  `).join('');
}

function centerTextPlugin(items) {
  const total = items.reduce((acc, item) => acc + (Number(item.unidades) || 0), 0);
  return {
    id: `centerText-${Date.now()}`,
    afterDraw(chart) {
      const { ctx, chartArea } = chart;
      if (!chartArea) return;
      const x = (chartArea.left + chartArea.right) / 2;
      const y = (chartArea.top + chartArea.bottom) / 2;
      ctx.save();
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillStyle = '#17233c';
      ctx.font = '700 13px Inter, sans-serif';
      ctx.fillText(fmt(total), x, y - 5);
      ctx.fillStyle = '#8a94a7';
      ctx.font = '8px Inter, sans-serif';
      ctx.fillText('unidades', x, y + 9);
      ctx.restore();
    },
  };
}

function renderAlcaldiaChart(items) {
  if (alcaldiaChart) alcaldiaChart.destroy();

  alcaldiaChart = new Chart($('alcaldia-chart'), {
    type: 'bar',
    data: {
      labels: items.map((i) => i.nombre),
      datasets: [{
        data: items.map((i) => Number(i.unidades) || 0),
        backgroundColor: '#6551df',
        borderRadius: 5,
        barThickness: 8,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      indexAxis: 'y',
      scales: {
        x: {
          beginAtZero: true,
          grid: { color: '#eef1f6' },
          border: { display: false },
          ticks: {
            color: '#8690a3',
            font: { size: 8 },
            callback: (value) => compactNumber(value),
          },
        },
        y: {
          grid: { display: false },
          border: { display: false },
          ticks: { color: '#59667d', font: { size: 8 } },
        },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (ctx) => `${fmt(ctx.raw)} unidades`,
          },
        },
      },
    },
  });
}

async function loadAlcaldiasLayer() {
  alcaldiasGeoJSON = await api('/alcaldias/geojson');
  await updateAlcaldiaLayerStyle();
}

async function updateAlcaldiaLayerStyle() {
  if (!alcaldiasGeoJSON) return;
  if (alcaldiaLayer) alcaldiaLayer.remove();

  const selectedId = Number($('filter-alcaldia').value || 0);
  alcaldiaLayer = L.geoJSON(alcaldiasGeoJSON, {
    style: (feature) => {
      const selected = selectedId && Number(feature.properties.id) === selectedId;
      return {
        color: selected ? '#4638c7' : '#6558d9',
        weight: selected ? 2.2 : 1.1,
        fillColor: selected ? '#6558d9' : '#756be5',
        fillOpacity: selected ? 0.12 : 0.025,
      };
    },
    onEachFeature: (feature, layer) => {
      layer.bindTooltip(feature.properties.nombre, { sticky: true });
    },
  }).addTo(map);

  if (selectedId) {
    const selectedFeature = alcaldiasGeoJSON.features.find((f) => Number(f.properties.id) === selectedId);
    if (selectedFeature) {
      const temp = L.geoJSON(selectedFeature);
      try { map.fitBounds(temp.getBounds(), { padding: [18,18], maxZoom: 13 }); } catch (_) {}
    }
  } else if (alcaldiaLayer.getBounds().isValid()) {
    map.fitBounds(alcaldiaLayer.getBounds(), { padding: [15,15], maxZoom: 11 });
  }
}

async function loadUnits() {
  const params = currentQuery();
  params.set('limit', $('filter-limit').value);
  const geo = await api(`/unidades?${params.toString()}`);

  if (unitLayer) unitLayer.remove();
  unitLayer = L.geoJSON(geo, {
    pointToLayer: (_feature, latlng) => L.circleMarker(latlng, {
      radius: 2.7,
      color: '#2f6fdb',
      weight: .4,
      fillColor: '#3b82f6',
      fillOpacity: .76,
    }),
    onEachFeature: (feature, layer) => {
      const p = feature.properties;
      layer.bindPopup(`
        <strong class="popup-title">${escapeHtml(p.nombre || 'Unidad económica')}</strong>
        <div class="popup-meta">${escapeHtml(p.codigo_scian || '—')} · ${escapeHtml(p.actividad || 'Sin actividad')}</div>
        <div class="popup-meta">${escapeHtml(p.alcaldia || '')}</div>
        <button class="popup-button" onclick="openUnit(${Number(p.id)})">Ver detalle</button>
      `);
    },
  }).addTo(map);
}

async function openUnit(id) {
  try {
    const u = await api(`/unidades/${id}`);
    $('unit-detail').innerHTML = `
      <h3>${escapeHtml(u.nombre || 'Unidad económica')}</h3>
      <p><strong>SCIAN:</strong> ${escapeHtml(u.codigo_scian || '—')}<br>
      <strong>Actividad:</strong> ${escapeHtml(u.actividad || '—')}<br>
      <strong>Sector:</strong> ${escapeHtml(u.sector || '—')}<br>
      <strong>Alcaldía:</strong> ${escapeHtml(u.alcaldia || '—')}<br>
      <strong>Coordenadas:</strong> ${u.lat}, ${u.lon}</p>
    `;
    switchView('detalle');
  } catch (err) {
    console.error(err);
  }
}
window.openUnit = openUnit;

function updateQueryTime(value) {
  const date = value ? new Date(value) : new Date();
  $('last-query').textContent = new Intl.DateTimeFormat('es-MX', {
    dateStyle: 'short',
    timeStyle: 'short',
  }).format(date);
}

function setDashboardLoading(isLoading) {
  $('apply-filters').disabled = isLoading;
  $('apply-filters').textContent = isLoading ? 'Actualizando…' : 'Aplicar filtros';
}

function renderDashboardError(message) {
  $('summary-total').textContent = '—';
  $('summary-alcaldias').textContent = '—';
  $('summary-activity-code').textContent = '—';
  $('summary-sector').textContent = '—';
  $('top-activities-table').innerHTML = `<tr><td colspan="4" class="empty-cell">No se pudieron cargar los datos: ${escapeHtml(message)}</td></tr>`;
  if (sectorChart) sectorChart.destroy();
  if (alcaldiaChart) alcaldiaChart.destroy();
  $('sector-legend').innerHTML = '<p class="muted">Sin datos.</p>';
}

function clearFilters() {
  $('filter-alcaldia').value = '';
  $('filter-sector').value = '';
  $('filter-actividad').value = '';
  $('filter-limit').value = '1200';
  refreshActivitiesBySector().then(loadDashboard);
}

function onPredictionClick(e) {
  selectedPredictionPoint = e.latlng;
  if (predictionMarker) predictionMarker.remove();
  predictionMarker = L.marker(e.latlng).addTo(predictionMap);
  $('pred-lat').textContent = e.latlng.lat.toFixed(6);
  $('pred-lon').textContent = e.latlng.lng.toFixed(6);
  $('pred-nearby').textContent = '—';
  $('pred-dominant').textContent = '—';
  $('predict-btn').disabled = false;
}

async function runPrediction() {
  if (!selectedPredictionPoint) return;
  $('prediction-message').textContent = 'Analizando entorno espacial…';
  try {
    const result = await api('/predicciones', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ lat: selectedPredictionPoint.lat, lon: selectedPredictionPoint.lng }),
    });
    $('pred-nearby').textContent = fmt(result.nearby_units);
    $('pred-dominant').textContent = result.dominant_activity || 'Sin actividad cercana';
    $('prediction-message').textContent = result.message;
  } catch (err) {
    $('prediction-message').textContent = `Error: ${err.message}`;
  }
}

function switchView(name) {
  document.querySelectorAll('.view').forEach((v) => v.classList.remove('active'));
  document.querySelectorAll('.nav-item[data-view]').forEach((v) => v.classList.remove('active'));
  $(`view-${name}`).classList.add('active');
  document.querySelector(`.nav-item[data-view="${name}"]`)?.classList.add('active');

  const labels = {
    dashboard: 'Dashboard principal',
    alcaldia: 'Consulta por alcaldía',
    detalle: 'Detalle de unidad económica',
    prediccion: 'Módulo de predicción',
  };

  $('page-title').textContent = labels[name];
  $('breadcrumb-current').textContent = labels[name];

  setTimeout(() => {
    if (name === 'dashboard') map.invalidateSize();
    if (name === 'prediccion') predictionMap.invalidateSize();
  }, 40);
}

function compactNumber(value) {
  return new Intl.NumberFormat('es-MX', { notation: 'compact', maximumFractionDigits: 1 }).format(value);
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

document.querySelectorAll('.nav-item[data-view]').forEach((btn) => {
  btn.addEventListener('click', () => switchView(btn.dataset.view));
});

$('apply-filters').addEventListener('click', loadDashboard);
$('clear-filters').addEventListener('click', clearFilters);
$('filter-sector').addEventListener('change', refreshActivitiesBySector);
$('predict-btn').addEventListener('click', runPrediction);

initMaps();
bootstrap();
