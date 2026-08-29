const API = '/api';

let map;
let unitLayer;
let alcaldiaLayer;
let predictionMap;
let alcaldiaMap;
let alcaldiaUnitLayer;
let alcaldiaBoundaryLayer;
let alcaldiaMapViewportEnabled = false;
let alcaldiaMapReloadTimer = null;
let alcaldiaScianChart;
let alcaldiaComparisonChart;
let predictionMarker;
let selectedPredictionPoint = null;
let sectorChart;
let alcaldiaChart;
let alcaldiasGeoJSON = null;
let mapViewportEnabled = false;
let mapReloadTimer = null;
let alcaldiaLoadVersion = 0;

const $ = (id) => document.getElementById(id);
const fmt = (value) => new Intl.NumberFormat('es-MX').format(Number(value) || 0);
const pct = (value, digits = 1) => `${Number(value || 0).toFixed(digits)}%`;

async function api(path, options) {
  const res = await fetch(`${API}${path}`, options);
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

function initMaps() {
  map = L.map('map', { zoomControl: true, preferCanvas: true }).setView([19.4326, -99.1332], 10);
  predictionMap = L.map('prediction-map').setView([19.4326, -99.1332], 10);
  alcaldiaMap = L.map('alcaldia-map', { zoomControl: true, preferCanvas: true }).setView([19.4326, -99.1332], 10);

  const tiles = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
  const attribution = '&copy; OpenStreetMap contributors';
  L.tileLayer(tiles, { attribution, maxZoom: 19 }).addTo(map);
  L.tileLayer(tiles, { attribution, maxZoom: 19 }).addTo(predictionMap);
  L.tileLayer(tiles, { attribution, maxZoom: 19 }).addTo(alcaldiaMap);

  predictionMap.on('click', onPredictionClick);

  map.on('moveend', () => {
    if (!mapViewportEnabled) return;
    clearTimeout(mapReloadTimer);
    mapReloadTimer = setTimeout(() => loadUnits().catch(console.error), 220);
  });

  alcaldiaMap.on('moveend', () => {
    if (!alcaldiaMapViewportEnabled || !$('alcaldia-select').value) return;
    clearTimeout(alcaldiaMapReloadTimer);
    alcaldiaMapReloadTimer = setTimeout(() => loadAlcaldiaUnits().catch(console.error), 220);
  });
}

async function bootstrap() {
  await checkHealth();

  try {
    const [alcaldias, sectores, actividades] = await Promise.all([
      api('/alcaldias'),
      api('/sectores'),
      api('/actividades'),
    ]);

    $('alcaldia-select').innerHTML = '';
    alcaldias.forEach((a) => {
      $('filter-alcaldia').insertAdjacentHTML('beforeend', `<option value="${a.id}">${escapeHtml(a.nombre)}</option>`);
      $('alcaldia-select').insertAdjacentHTML('beforeend', `<option value="${a.id}">${escapeHtml(a.nombre)}</option>`);
    });

    sectores.forEach((s) => {
      $('filter-sector').insertAdjacentHTML('beforeend', `<option value="${s.id}">${escapeHtml(s.nombre)}</option>`);
    });

    renderActivityOptions(actividades);
    if (alcaldias.length) {
      const preferred =
        alcaldias.find((a) => a.nombre === 'Benito Juárez') || alcaldias[0];

      $('alcaldia-select').value = String(preferred.id);
    }

    await loadAlcaldiasLayer();

    await Promise.all([
      loadDashboard(),
      loadDataUpdateStatus(),
    ]);

    mapViewportEnabled = true;
    if (
      $('view-alcaldia').classList.contains('active') &&
      $('alcaldia-select').value
    ) {
      await loadAlcaldiaModule();
    }
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
    await updateAlcaldiaLayerStyle();
    await loadUnits();
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
            label: (ctx) => `${ctx.label}: ${fmt(ctx.raw)} unidades (${pct(items[ctx.dataIndex]?.porcentaje, 2)})`,
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
      <span class="legend-value"><b>${fmt(item.unidades)}</b><strong>${pct(item.porcentaje, 2)}</strong></span>
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


function selectedAlcaldiaFeature() {
  if (!alcaldiasGeoJSON) return null;
  const selectedId = Number($('alcaldia-select').value || 0);
  return alcaldiasGeoJSON.features.find((f) => Number(f.properties.id) === selectedId) || null;
}

function renderAlcaldiaBoundary({ fit = false } = {}) {
  const feature = selectedAlcaldiaFeature();
  if (!feature || !alcaldiaMap) return;
  if (alcaldiaBoundaryLayer) alcaldiaBoundaryLayer.remove();

  alcaldiaBoundaryLayer = L.geoJSON(feature, {
    style: {
      color: '#5141d6',
      weight: 2,
      fillColor: '#6b5ce7',
      fillOpacity: .10,
    },
  }).addTo(alcaldiaMap);

  if (fit && alcaldiaBoundaryLayer.getBounds().isValid()) {
    alcaldiaMapViewportEnabled = false;
    alcaldiaMap.fitBounds(alcaldiaBoundaryLayer.getBounds(), { padding: [18, 18], maxZoom: 13 });
    setTimeout(() => { alcaldiaMapViewportEnabled = true; }, 300);
  }
}

async function loadAlcaldiaModule() {
  const alcaldiaId = Number($('alcaldia-select').value || 0);

  if (!alcaldiaId) {
    return;
  }
  const loadVersion = ++alcaldiaLoadVersion;

  clearTimeout(alcaldiaMapReloadTimer);
  alcaldiaMapViewportEnabled = false;

  $('alcaldia-map-status').textContent = 'Cargando alcaldía…';

  try {
    const summary = await api(
      `/alcaldias/${alcaldiaId}/resumen`
    );
    if (
      loadVersion !== alcaldiaLoadVersion ||
      Number($('alcaldia-select').value || 0) !== alcaldiaId
    ) {
      return;
    }

    renderAlcaldiaSummary(summary);
    renderAlcaldiaTopActivities(summary.top_actividades || []);
    renderAlcaldiaScianChart(summary.distribucion_scian || []);

    renderAlcaldiaComparisonChart(
      summary.distribucion_alcaldias || [],
      alcaldiaId
    );
    renderAlcaldiaBoundary({
      fit: true,
    });
    setTimeout(() => {
      if (
        loadVersion !== alcaldiaLoadVersion ||
        Number($('alcaldia-select').value || 0) !== alcaldiaId
      ) {
        return;
      }

      alcaldiaMap.invalidateSize();

      loadAlcaldiaUnits(alcaldiaId)
        .catch(console.error);

    }, 100);

  } catch (err) {
    if (loadVersion !== alcaldiaLoadVersion) {
      return;
    }

    console.error(err);
    renderAlcaldiaError(err.message);
  }
}

function renderAlcaldiaSummary(summary) {
  const alc = summary.alcaldia || {};
  $('alc-info-name').textContent = alc.nombre || '—';
  $('alc-info-cvegeo').textContent = alc.cvegeo || '—';
  $('alc-info-total').textContent = fmt(summary.total_unidades);
  $('alc-info-activities').textContent = `${fmt(summary.actividades_distintas)} de 20`;

  const activity = summary.actividad_lider;
  $('alc-info-leader').textContent = activity
    ? `${activity.codigo_scian} · ${activity.descripcion} (${fmt(activity.unidades)})`
    : '—';

  const sector = summary.sector_lider;
  $('alc-info-sector').textContent = sector
    ? `${sector.nombre} · ${fmt(sector.unidades)} (${pct(sector.porcentaje, 2)})`
    : '—';

  $('alc-info-rank').textContent = summary.ranking_cdmx
    ? `${summary.ranking_cdmx}.° de 16`
    : '—';
}

function renderAlcaldiaTopActivities(items) {
  const tbody = $('alcaldia-top-table');
  if (!items.length) {
    tbody.innerHTML = '<tr><td colspan="4" class="empty-cell">No hay registros para esta alcaldía.</td></tr>';
    return;
  }
  tbody.innerHTML = items.map((item) => `
    <tr>
      <td><span class="activity-code">${escapeHtml(item.codigo_scian)}</span></td>
      <td class="activity-name" title="${escapeHtml(item.descripcion)}">${escapeHtml(item.descripcion)}</td>
      <td class="numeric"><strong>${fmt(item.unidades)}</strong></td>
      <td class="numeric">${pct(item.porcentaje, 2)}</td>
    </tr>
  `).join('');
}

function renderAlcaldiaScianChart(items) {
  if (alcaldiaScianChart) alcaldiaScianChart.destroy();

  alcaldiaScianChart = new Chart($('alcaldia-scian-chart'), {
    type: 'bar',
    data: {
      labels: items.map((i) => i.codigo_scian),
      datasets: [{
        data: items.map((i) => Number(i.unidades) || 0),
        backgroundColor: '#5f50df',
        borderRadius: 4,
        maxBarThickness: 22,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: {
          grid: { display: false },
          border: { display: false },
          ticks: { color: '#6c778d', font: { size: 8 }, maxRotation: 0, autoSkip: false },
        },
        y: {
          beginAtZero: true,
          grid: { color: '#eef1f6' },
          border: { display: false },
          ticks: { color: '#8690a3', font: { size: 8 }, callback: (value) => compactNumber(value) },
        },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: (ctx) => {
              const item = items[ctx[0]?.dataIndex];
              return item ? `${item.codigo_scian} · ${item.descripcion}` : '';
            },
            label: (ctx) => `${fmt(ctx.raw)} unidades · ${pct(items[ctx.dataIndex]?.porcentaje, 2)}`,
          },
        },
      },
    },
  });
}

function renderAlcaldiaComparisonChart(items, selectedId) {
  if (alcaldiaComparisonChart) alcaldiaComparisonChart.destroy();

  const top = items.slice(0, 5);
  const selected = items.find((item) => Number(item.id) === Number(selectedId));
  const shown = [...top];
  if (selected && !top.some((item) => Number(item.id) === Number(selectedId))) shown.push(selected);

  const selectedOutsideTop = selected && !top.some((item) => Number(item.id) === Number(selectedId));
  $('alcaldia-comparison-note').textContent = selectedOutsideTop
    ? 'Top 5 alcaldías y la demarcación seleccionada para contexto.'
    : 'Top 5 alcaldías por número de unidades; la seleccionada está resaltada.';

  alcaldiaComparisonChart = new Chart($('alcaldia-comparison-chart'), {
    type: 'bar',
    data: {
      labels: shown.map((i) => i.nombre),
      datasets: [{
        data: shown.map((i) => Number(i.unidades) || 0),
        backgroundColor: shown.map((i) => Number(i.id) === Number(selectedId) ? '#5f50df' : '#c9c4f5'),
        borderRadius: 5,
        barThickness: 12,
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
          ticks: { color: '#8690a3', font: { size: 8 }, callback: (value) => compactNumber(value) },
        },
        y: {
          grid: { display: false },
          border: { display: false },
          ticks: { color: '#59667d', font: { size: 8 } },
        },
      },
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: (ctx) => `${fmt(ctx.raw)} unidades` } },
      },
    },
  });
}

async function loadAlcaldiaUnits(requestedAlcaldiaId = null) {
  const alcaldiaId = Number(
    requestedAlcaldiaId ||
    $('alcaldia-select').value ||
    0
  );

  if (!alcaldiaId || !alcaldiaMap) {
    return;
  }

  const bounds = alcaldiaMap.getBounds();

  const params = new URLSearchParams({
    alcaldia_id: String(alcaldiaId),
    west: bounds.getWest().toFixed(7),
    south: bounds.getSouth().toFixed(7),
    east: bounds.getEast().toFixed(7),
    north: bounds.getNorth().toFixed(7),
    zoom: String(alcaldiaMap.getZoom()),
  });

  $('alcaldia-map-status').textContent =
    'Actualizando mapa…';

  const geo = await api(
    `/unidades/mapa?${params.toString()}`
  );
  if (
    Number($('alcaldia-select').value || 0) !== alcaldiaId
  ) {
    return;
  }

  if (alcaldiaUnitLayer) {
    alcaldiaUnitLayer.remove();
  }

  alcaldiaUnitLayer = L.geoJSON(geo, {

    pointToLayer: (feature, latlng) => {
      const p = feature.properties || {};

      if (p.tipo === 'cluster') {
  const count = Number(p.unidades) || 1;

  const size = Math.min(
  38,
  24 + Math.log10(count + 1) * 4
);

  return L.marker(latlng, {
    icon: L.divIcon({
      className: 'map-cluster-marker',
      html: `<span>${fmt(count)}</span>`,
      iconSize: [size, size],
      iconAnchor: [size / 2, size / 2],
    }),
  });
}

      return L.circleMarker(latlng, {
        radius: 2.7,
        color: '#2f6fdb',
        weight: 0.4,
        fillColor: '#3b82f6',
        fillOpacity: 0.76,
      });
    },

    onEachFeature: (feature, layer) => {
      const p = feature.properties || {};

      if (p.tipo === 'cluster') {
        layer.bindTooltip(
          `
          <strong>${fmt(p.unidades)} unidades</strong>
          <br>
          Acerca el mapa para ver mayor detalle.
          `,
          {
            sticky: true,
          }
        );

        return;
      }

      layer.bindPopup(`
        <strong class="popup-title">
          ${escapeHtml(p.nombre || 'Unidad económica')}
        </strong>

        <div class="popup-meta">
          ${escapeHtml(p.codigo_scian || '—')}
          ·
          ${escapeHtml(p.actividad || 'Sin actividad')}
        </div>

        <div class="popup-meta">
          ${escapeHtml(p.alcaldia || '')}
        </div>

        <button
          class="popup-button"
          onclick="openUnit(${Number(p.id)})"
        >
          Ver detalle
        </button>
      `);
    },

  }).addTo(alcaldiaMap);
  if (alcaldiaBoundaryLayer) {
    alcaldiaBoundaryLayer.bringToFront();
  }

  const meta = geo.meta || {};

  if (meta.mode === 'clusters') {

    $('alcaldia-map-status').textContent =
      `${fmt(meta.returned)} agrupaciones · ` +
      `${fmt(meta.represented)} unidades representadas`;

  } else if (meta.truncated) {

    $('alcaldia-map-status').textContent =
      `Mostrando ${fmt(meta.returned)} de ` +
      `${fmt(meta.total_in_view)} unidades visibles · ` +
      `acerca el zoom`;

  } else {

    $('alcaldia-map-status').textContent =
      `${fmt(meta.returned)} unidades visibles`;
  }
}

function renderAlcaldiaError(message) {
  ['alc-info-name','alc-info-cvegeo','alc-info-total','alc-info-activities','alc-info-leader','alc-info-sector','alc-info-rank']
    .forEach((id) => { $(id).textContent = '—'; });
  $('alcaldia-top-table').innerHTML = `<tr><td colspan="4" class="empty-cell">No se pudo cargar la alcaldía: ${escapeHtml(message)}</td></tr>`;
  $('alcaldia-map-status').textContent = 'No se pudieron cargar los datos.';
  if (alcaldiaScianChart) alcaldiaScianChart.destroy();
  if (alcaldiaComparisonChart) alcaldiaComparisonChart.destroy();
}

async function loadUnits() {
  const params = currentQuery();
  const bounds = map.getBounds();
  params.set('west', bounds.getWest().toFixed(7));
  params.set('south', bounds.getSouth().toFixed(7));
  params.set('east', bounds.getEast().toFixed(7));
  params.set('north', bounds.getNorth().toFixed(7));
  params.set('zoom', String(map.getZoom()));

  $('map-status').textContent = 'Actualizando mapa…';
  const geo = await api(`/unidades/mapa?${params.toString()}`);

  if (unitLayer) unitLayer.remove();
  unitLayer = L.geoJSON(geo, {
    pointToLayer: (feature, latlng) => {
      const p = feature.properties || {};
      if (p.tipo === 'cluster') {
        const count = Number(p.unidades) || 1;
        const radius = Math.min(18, 5 + Math.log10(count + 1) * 3.2);
        return L.circleMarker(latlng, {
          radius,
          color: '#2949cf',
          weight: 1,
          fillColor: '#3155e7',
          fillOpacity: .5,
        });
      }
      return L.circleMarker(latlng, {
        radius: 2.7,
        color: '#2f6fdb',
        weight: .4,
        fillColor: '#3b82f6',
        fillOpacity: .76,
      });
    },
    onEachFeature: (feature, layer) => {
      const p = feature.properties || {};
      if (p.tipo === 'cluster') {
        layer.bindTooltip(
          `<strong>${fmt(p.unidades)} unidades</strong><br>Acerca el mapa para ver mayor detalle.`,
          { sticky: true }
        );
        return;
      }
      layer.bindPopup(`
        <strong class="popup-title">${escapeHtml(p.nombre || 'Unidad económica')}</strong>
        <div class="popup-meta">${escapeHtml(p.codigo_scian || '—')} · ${escapeHtml(p.actividad || 'Sin actividad')}</div>
        <div class="popup-meta">${escapeHtml(p.alcaldia || '')}</div>
        <button class="popup-button" onclick="openUnit(${Number(p.id)})">Ver detalle</button>
      `);
    },
  }).addTo(map);

  const meta = geo.meta || {};
  if (meta.mode === 'clusters') {
    $('map-status').textContent = `${fmt(meta.returned)} agrupaciones · ${fmt(meta.represented)} unidades representadas en el área visible`;
  } else if (meta.truncated) {
    $('map-status').textContent = `Mostrando ${fmt(meta.returned)} de ${fmt(meta.total_in_view)} unidades visibles · acerca el zoom para verlas todas`;
  } else {
    $('map-status').textContent = `${fmt(meta.returned)} unidades visibles`;
  }
}

async function openUnit(id) {
  try {
    const u = await api(`/unidades/${id}`);
    $('unit-detail').innerHTML = `
      <h3>${escapeHtml(u.nombre || 'Unidad económica')}</h3>
      <p><strong>ID DENUE:</strong> ${escapeHtml(u.id_denue || '—')}<br>
      <strong>SCIAN:</strong> ${escapeHtml(u.codigo_scian || '—')}<br>
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

async function loadDataUpdateStatus() {
  try {
    const state = await api('/datos/estado-actualizacion');
    if (!state.last_success_at) {
      $('last-query').textContent = state.status === 'failed' ? 'Error de actualización' : 'Pendiente';
      return;
    }
    const date = new Date(state.last_success_at);
    $('last-query').textContent = new Intl.DateTimeFormat('es-MX', {
      dateStyle: 'short',
      timeStyle: 'short',
    }).format(date);
  } catch (err) {
    console.error(err);
    $('last-query').textContent = 'No disponible';
  }
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
  const subtitles = {
    dashboard: 'Panorama general de las unidades económicas registradas en la Ciudad de México.',
    alcaldia: 'Análisis detallado de las unidades económicas de una alcaldía seleccionada.',
    detalle: 'Información individual y contexto territorial de una unidad económica.',
    prediccion: 'Selecciona una ubicación para analizar su entorno económico.',
  };

  $('page-title').textContent = labels[name];
  $('breadcrumb-current').textContent = labels[name];
  document.querySelector('.page-subtitle').textContent = subtitles[name];

  if (name === 'alcaldia') {
    if ($('filter-alcaldia').value) $('alcaldia-select').value = $('filter-alcaldia').value;
    loadAlcaldiaModule().catch(console.error);
  }

  setTimeout(() => {
    if (name === 'dashboard') map.invalidateSize();
    if (name === 'alcaldia') alcaldiaMap.invalidateSize();
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
$('alcaldia-select').addEventListener('change', () => loadAlcaldiaModule().catch(console.error));
$('back-dashboard').addEventListener('click', () => switchView('dashboard'));
$('predict-btn').addEventListener('click', runPrediction);

initMaps();
bootstrap();
