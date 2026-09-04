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
let predictionCellLayer = null;

let selectedPredictionPoint = null;
let lastPredictionResult = null;
let sectorChart;
let alcaldiaChart;
let alcaldiasGeoJSON = null;
let mapViewportEnabled = false;
let mapReloadTimer = null;
let alcaldiaLoadVersion = 0;
let detailMap;
let detailMarker;
let detailBoundaryLayer;

let currentUnitId = null;
let lastViewBeforeDetail = 'dashboard';

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

  detailMap = L.map(
  'detail-map',
  {
    zoomControl: true,
    preferCanvas: true
  }
).setView(
  [19.4326, -99.1332],
  12
);
  const tiles = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
  const attribution = '&copy; OpenStreetMap contributors';
  L.tileLayer(tiles, { attribution, maxZoom: 19 }).addTo(map);
  L.tileLayer(tiles, { attribution, maxZoom: 19 }).addTo(predictionMap);
  L.tileLayer(tiles, { attribution, maxZoom: 19 }).addTo(alcaldiaMap);
  L.tileLayer(
  tiles,
  {
    attribution,
    maxZoom: 19
  }
).addTo(detailMap);

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

function detailText(id, value) {

  const el = $(id);

  if (!el) {
    return;
  }

  const text = String(
    value ?? ''
  ).trim();

  el.textContent = text || '—';
}


function detailDistance(value) {
  const n = Number(value);

  if (!Number.isFinite(n)) {
    return '—';
  }

  if (n >= 1000) {
    return `${(n / 1000).toLocaleString(
      'es-MX',
      {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
      }
    )} km`;
  }

  return `${n.toLocaleString(
    'es-MX',
    {
      maximumFractionDigits: 2
    }
  )} m`;
}


function detailAddress(u) {

  const tipoVial = String(
    u.tipo_vial ?? ''
  ).trim();

  const nombreVial = String(
    u.nom_vial ?? ''
  ).trim();


  let vialidad = nombreVial;
  if (tipoVial && nombreVial) {

    const tipoUpper =
      tipoVial.toUpperCase();

    const nombreUpper =
      nombreVial.toUpperCase();

    if (
      !nombreUpper.startsWith(
        `${tipoUpper} `
      ) &&
      nombreUpper !== tipoUpper
    ) {

      vialidad =
        `${tipoVial} ${nombreVial}`;
    }

  } else if (tipoVial) {

    vialidad = tipoVial;
  }


  const exterior = [
    u.numero_ext,
    u.letra_ext
  ]
    .map((v) =>
      String(v ?? '').trim()
    )
    .filter(Boolean)
    .join(' ');


  const interiorParts = [
    u.numero_int,
    u.letra_int
  ]
    .map((v) =>
      String(v ?? '').trim()
    )
    .filter(Boolean);


  const interior =
    interiorParts.length
      ? `Int. ${interiorParts.join(' ')}`
      : '';


  const settlement = [
    u.tipo_asent,
    u.nomb_asent
  ]
    .map((v) =>
      String(v ?? '').trim()
    )
    .filter(Boolean)
    .join(' ');


  return [
    vialidad,
    exterior,
    interior,
    settlement
  ]
    .filter(Boolean)
    .join(', ')
    || '—';
}


function detailLink(
  id,
  value,
  type
) {

  const el = $(id);

  if (!el) {
    return;
  }

  el.replaceChildren();

  const raw = String(
    value ?? ''
  ).trim();


  if (!raw) {

    el.textContent = '—';

    return;
  }


  let href = null;


  if (type === 'email') {

    href = `mailto:${raw}`;

  } else if (type === 'phone') {

    href =
      `tel:${raw.replace(
        /[^+\d]/g,
        ''
      )}`;

  } else if (type === 'web') {

    try {

      const candidate =
        /^https?:\/\//i.test(raw)
          ? raw
          : `https://${raw}`;

      const url =
        new URL(candidate);

      if (
        [
          'http:',
          'https:'
        ].includes(
          url.protocol
        )
      ) {

        href = url.href;
      }

    } catch (_) {
    }
  }


  if (!href) {

    el.textContent = raw;

    return;
  }


  const a =
    document.createElement('a');

  a.textContent = raw;

  a.href = href;

  a.className =
    'detail-link';


  if (type === 'web') {

    a.target = '_blank';

    a.rel =
      'noopener noreferrer';
  }


  el.appendChild(a);
}


function renderDetailMap(u) {

  if (!detailMap) {
    return;
  }


  if (detailMarker) {
    detailMarker.remove();
  }


  if (detailBoundaryLayer) {
    detailBoundaryLayer.remove();
  }


  const lat =
    Number(u.lat);

  const lon =
    Number(u.lon);


  if (
    !Number.isFinite(lat) ||
    !Number.isFinite(lon)
  ) {

    return;
  }
  const feature =
    alcaldiasGeoJSON
      ?.features
      ?.find(
        (f) =>
          Number(
            f.properties?.id
          ) ===
          Number(
            u.alcaldia_id
          )
      );


  if (feature) {

    detailBoundaryLayer =
      L.geoJSON(
        feature,
        {
          style: {

            color: '#6558d9',

            weight: 1.6,

            fillColor:
              '#756be5',

            fillOpacity:
              0.04
          }
        }
      )
      .addTo(detailMap);
  }


  detailMarker =
    L.marker([
      lat,
      lon
    ])
    .addTo(detailMap)
    .bindPopup(`
      <strong class="popup-title">
        ${escapeHtml(
          u.nombre ||
          'Unidad económica'
        )}
      </strong>

      <div class="popup-meta">
        ${escapeHtml(
          u.codigo_scian_denue ||
          u.codigo_scian_sistema ||
          '—'
        )}
        ·
        ${escapeHtml(
          u.actividad_denue ||
          u.actividad_sistema ||
          '—'
        )}
      </div>
    `);


  detailMap.setView(
    [
      lat,
      lon
    ],
    17
  );


  setTimeout(
    () =>
      detailMap.invalidateSize(),
    60
  );
}


function renderNearbyUnits(items) {

  const body =
    $('detail-nearby-body');


  if (!body) {
    return;
  }


  if (!items?.length) {

    body.innerHTML = `
      <tr>

        <td
          colspan="5"
          class="empty-cell"
        >
          No hay otras unidades
          en la misma celda.
        </td>

      </tr>
    `;

    return;
  }


  body.innerHTML =
    items
      .map(
        (item) => `
          <tr>

            <td>
              ${escapeHtml(
                item.id_denue ||
                '—'
              )}
            </td>

            <td
              class="detail-nearby-name"
              title="${escapeHtml(
                item.nombre ||
                ''
              )}"
            >
              ${escapeHtml(
                item.nombre ||
                'Sin nombre'
              )}
            </td>

            <td>

              <span
                class="activity-code"
              >
                ${escapeHtml(
                  item.codigo_scian ||
                  '—'
                )}
              </span>

            </td>

            <td class="numeric">

              ${detailDistance(
                item.distancia_m
              )}

            </td>

            <td class="numeric">

              <button
                class="detail-row-button"
                type="button"
                onclick="openUnit(
                  ${Number(item.id)}
                )"
              >
                Ver
              </button>

            </td>

          </tr>
        `
      )
      .join('');
}


function renderUnitDetail(u) {

  currentUnitId =
    Number(u.id);


  $('detail-empty')
    .classList
    .add('hidden');


  $('detail-content')
    .classList
    .remove('hidden');
  detailText(
    'detail-name',
    u.nombre ||
    'Unidad económica'
  );


  detailText(
    'detail-activity-subtitle',

    `${
      u.codigo_scian_denue ||
      u.codigo_scian_sistema ||
      '—'
    } · ${
      u.actividad_denue ||
      u.actividad_sistema ||
      'Actividad no disponible'
    }`
  );

  detailText(
    'detail-id-denue',
    u.id_denue
  );

  detailText(
    'detail-clee',
    u.clee
  );

  detailText(
    'detail-razon-social',
    u.raz_social
  );

  detailText(
    'detail-per-ocu',
    u.per_ocu
  );

  detailText(
    'detail-tipo-unidad',
    u.tipounieco
  );

  detailText(
    'detail-fecha-alta',
    u.fecha_alta
  );

  detailText(
    'detail-alcaldia',
    u.alcaldia
  );


  const lat =
    Number(u.lat);

  const lon =
    Number(u.lon);


  detailText(
    'detail-coords',

    Number.isFinite(lat) &&
    Number.isFinite(lon)

      ? `${lat.toFixed(6)}, ${lon.toFixed(6)}`

      : '—'
  );


  detailText(
    'detail-border',
    detailDistance(
      u.dist_to_border
    )
  );
  detailText(
    'detail-scian-full',
    u.codigo_scian_denue
  );

  detailText(
    'detail-scian-system',
    u.codigo_scian_sistema
  );

  detailText(
    'detail-activity-denue',
    u.actividad_denue
  );

  detailText(
    'detail-activity-system',
    u.actividad_sistema
  );

  detailText(
    'detail-sector',
    u.sector
  );
  detailText(
    'detail-cvegeo',
    u.alcaldia_cvegeo
  );

  detailText(
    'detail-address',
    detailAddress(u)
  );

  detailText(
    'detail-cp',
    u.cod_postal
  );

  detailText(
    'detail-ageb-manzana',

    `${
      u.ageb ||
      '—'
    } / ${
      u.manzana ||
      '—'
    }`
  );

  detailText(
    'detail-cell-id',
    u.cell_id
  );

  detailText(
    'detail-cell-xy',

    `${
      u.cell_x ??
      '—'
    } / ${
      u.cell_y ??
      '—'
    }`
  );

  detailText(
  'detail-same-cell',
  `${fmt(u.unidades_misma_celda)} (incluye esta unidad)`
);
  const nearbyTotal = Math.max(
  0,
  Number(u.unidades_misma_celda || 0) - 1
);

const nearbyShown =
  Array.isArray(u.unidades_cercanas)
    ? u.unidades_cercanas.length
    : 0;


detailText(
  'detail-nearby-summary',

  nearbyTotal > 0
    ? `Mostrando las ${fmt(nearbyShown)} unidades más cercanas de ${fmt(nearbyTotal)} establecimientos adicionales dentro de la celda espacial de 300 m.`
    : 'No existen otros establecimientos registrados dentro de esta celda espacial.'
);
  detailLink(
    'detail-phone',
    u.telefono,
    'phone'
  );

  detailLink(
    'detail-email',
    u.correoelec,
    'email'
  );

  detailLink(
    'detail-web',
    u.www,
    'web'
  );

  renderNearbyUnits(
    u.unidades_cercanas ||
    []
  );
  renderDetailMap(u);
}


async function openUnit(id) {

  const activeView =
    document
      .querySelector(
        '.view.active'
      )
      ?.id
      ?.replace(
        'view-',
        ''
      );


  if (
    activeView &&
    activeView !== 'detalle'
  ) {

    lastViewBeforeDetail =
      activeView;
  }


  switchView(
    'detalle'
  );


  $('detail-empty')
    .classList
    .add('hidden');


  $('detail-content')
    .classList
    .remove('hidden');


  detailText(
    'detail-name',
    'Cargando unidad económica…'
  );


  detailText(
    'detail-activity-subtitle',
    'Consultando información DENUE y contexto espacial.'
  );


  try {

    const u =
      await api(
        `/unidades/${Number(id)}`
      );


    renderUnitDetail(u);

  } catch (err) {

    console.error(err);

    currentUnitId = null;


    $('detail-content')
      .classList
      .add('hidden');


    $('detail-empty')
      .classList
      .remove('hidden');


    $('detail-empty')
      .querySelector('p')
      .textContent =
        `No se pudo cargar la unidad económica: ${err.message}`;
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
function formatAboutDate(value) {

  if (!value) {
    return 'Pendiente';
  }

  const date =
    new Date(value);

  if (
    Number.isNaN(
      date.getTime()
    )
  ) {
    return 'No disponible';
  }

  return new Intl.DateTimeFormat(
    'es-MX',
    {
      dateStyle: 'medium',
      timeStyle: 'short'
    }
  ).format(date);
}


function renderAboutSyncStatus(state) {

  const element =
    $('about-sync-status');

  if (!element) {
    return;
  }

  const status =
    String(
      state?.status ??
      ''
    ).toLowerCase();


  let text =
    'Estado desconocido';

  let className =
    'pending';


  if (status === 'success') {

    text =
      'Actualización correcta';

    className =
      'success';

  } else if (
    status === 'running'
  ) {

    text =
      'Actualización en curso';

    className =
      'running';

  } else if (
    status === 'failed'
  ) {

    text =
      'Último intento con error';

    className =
      'error';

  } else if (
    status === 'pending' ||
    status === 'not_initialized'
  ) {

    text =
      'Pendiente';

    className =
      'pending';
  }


  element.className =
    `about-status-pill ${className}`;

  element.textContent =
    text;
}


async function loadAboutSystem() {
  detailText(
    'about-total',
    '…'
  );

  detailText(
    'about-alcaldias',
    '…'
  );

  detailText(
    'about-activities',
    '…'
  );

  detailText(
    'about-update',
    'Consultando…'
  );

  detailText(
    'about-sync-records',
    '…'
  );


  try {
    const [
      summary,
      actividades,
      state
    ] = await Promise.all([

      api('/dashboard/resumen'),

      api('/actividades'),

      api('/datos/estado-actualizacion')

    ]);
    detailText(
      'about-total',
      fmt(
        summary.total_unidades
      )
    );


    detailText(
      'about-alcaldias',
      fmt(
        summary.alcaldias_representadas
      )
    );


    detailText(
      'about-activities',
      fmt(
        Array.isArray(
          actividades
        )
          ? actividades.length
          : 0
      )
    );
    detailText(
      'about-update',
      formatAboutDate(
        state.last_success_at
      )
    );
    detailText(
      'about-sync-records',

      state.last_records != null

        ? `${fmt(
            state.last_records
          )} registros`

        : 'No disponible'
    );


    renderAboutSyncStatus(
      state
    );


  } catch (err) {

    console.error(
      'No se pudo cargar Acerca del sistema:',
      err
    );


    detailText(
      'about-total',
      'No disponible'
    );

    detailText(
      'about-alcaldias',
      'No disponible'
    );

    detailText(
      'about-activities',
      'No disponible'
    );

    detailText(
      'about-update',
      'No disponible'
    );

    detailText(
      'about-sync-records',
      'No disponible'
    );


    const status =
      $('about-sync-status');

    if (status) {

      status.className =
        'about-status-pill error';

      status.textContent =
        'API no disponible';
    }
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



function probabilityLabel(value, digits = 1) {

  const number = Number(value);

  if (!Number.isFinite(number)) {
    return '—';
  }

  return `${(number * 100).toFixed(digits)}%`;
}


function setPredictionResultEnabled(enabled) {

  const nav = $('prediction-result-nav');

  if (!nav) {
    return;
  }

  nav.disabled = !enabled;

  nav.classList.toggle(
    'disabled-nav',
    !enabled
  );

  nav.title = enabled
    ? 'Ver el último resultado de predicción'
    : 'Genera primero una predicción';
}

function clearPredictionCell() {

  if (
    predictionCellLayer &&
    predictionMap
  ) {

    predictionMap.removeLayer(
      predictionCellLayer
    );

    predictionCellLayer = null;
  }
}


function drawPredictionCell(
  cell,
  {
    fit = false
  } = {}
) {

  clearPredictionCell();


  if (
    !cell ||
    !Array.isArray(
      cell.polygon
    ) ||
    cell.polygon.length < 4
  ) {

    return;
  }


  const latLngs =
    cell.polygon
      .map(
        point => [
          Number(
            point.lat
          ),
          Number(
            point.lon
          ),
        ]
      )
      .filter(
        point =>
          Number.isFinite(
            point[0]
          )
          &&
          Number.isFinite(
            point[1]
          )
      );


  if (
    latLngs.length < 4
  ) {

    return;
  }


  predictionCellLayer =
    L
      .polygon(
        latLngs,
        {
          weight: 3,
          opacity: 0.9,
          fillOpacity: 0.12,
          dashArray: '7 5'
        }
      )
      .addTo(
        predictionMap
      );


  predictionCellLayer.bindTooltip(
    `
      <strong>Celda analizada</strong><br>
      ${cell.size_m} × ${cell.size_m} m<br>
      Celda ${cell.x}, ${cell.y}
    `,
    {
      sticky: true
    }
  );


  if (fit) {

    predictionMap.fitBounds(
      predictionCellLayer.getBounds(),
      {
        padding: [
          30,
          30
        ],
        maxZoom: 16
      }
    );
  }
}
function clearPredictionResult() {

  lastPredictionResult = null;

  setPredictionResultEnabled(
    false
  );
}


function setPredictionPoint(
  lat,
  lon,
  {
    centerMap = false,
    source = 'map'
  } = {}
) {

  const numericLat =
    Number(lat);

  const numericLon =
    Number(lon);

  if (
    !Number.isFinite(numericLat) ||
    !Number.isFinite(numericLon)
  ) {

    throw new Error(
      'Las coordenadas deben ser valores numéricos.'
    );
  }


  if (
    numericLat < -90 ||
    numericLat > 90
  ) {

    throw new Error(
      'La latitud debe estar entre -90 y 90.'
    );
  }


  if (
    numericLon < -180 ||
    numericLon > 180
  ) {

    throw new Error(
      'La longitud debe estar entre -180 y 180.'
    );
  }

  selectedPredictionPoint =
    L.latLng(
      numericLat,
      numericLon
    );
  clearPredictionCell();


  if (predictionMarker) {
    predictionMarker.remove();
  }


  predictionMarker =
    L
      .marker(
        selectedPredictionPoint
      )
      .addTo(
        predictionMap
      );

  if (centerMap) {

    const currentZoom =
      predictionMap.getZoom();

    predictionMap.setView(
      selectedPredictionPoint,
      Math.max(
        currentZoom,
        15
      )
    );
  }

  $('manual-pred-lat').value =
    numericLat.toFixed(6);

  $('manual-pred-lon').value =
    numericLon.toFixed(6);

  $('pred-lat').textContent =
    numericLat.toFixed(6);

  $('pred-lon').textContent =
    numericLon.toFixed(6);

  $('pred-nearby').textContent =
    '—';

  $('pred-dominant').textContent =
    '—';


  if (source === 'manual') {

    $('prediction-message').textContent =
      'Coordenadas ubicadas en el mapa. Presiona “Analizar punto seleccionado”.';

  } else {

    $('prediction-message').textContent =
      'Punto seleccionado en el mapa. Presiona “Analizar punto seleccionado”.';
  }


  $('manual-coordinate-error')
    .classList
    .add(
      'hidden'
    );

  $('manual-coordinate-error').textContent =
    '';


  $('predict-btn').disabled =
    false;
  clearPredictionResult();
}


function onPredictionClick(e) {

  try {

    setPredictionPoint(
      e.latlng.lat,
      e.latlng.lng,
      {
        centerMap: false,
        source: 'map'
      }
    );

  } catch (error) {

    $('prediction-message').textContent =
      error.message;
  }
}


function useManualPredictionCoordinates() {

  const latValue =
    $('manual-pred-lat')
      .value
      .trim();

  const lonValue =
    $('manual-pred-lon')
      .value
      .trim();


  const errorElement =
    $('manual-coordinate-error');


  if (
    latValue === '' ||
    lonValue === ''
  ) {

    errorElement.textContent =
      'Escribe la latitud y la longitud.';

    errorElement
      .classList
      .remove(
        'hidden'
      );

    return;
  }


  try {

    setPredictionPoint(
      latValue,
      lonValue,
      {
        centerMap: true,
        source: 'manual'
      }
    );

  } catch (error) {

    errorElement.textContent =
      error.message;

    errorElement
      .classList
      .remove(
        'hidden'
      );
  }
}


function renderPredictionResult(result) {

  if (
    !result ||
    !result.prediction
  ) {
    return;
  }

  const prediction = result.prediction;

  const ambiguity =
    result.ambiguity || null;

  const isAmbiguous =
    Boolean(
      ambiguity?.ambiguous
    );
  if (isAmbiguous) {

    $('result-activity').textContent =
      'Zona altamente ambigua';

    $('result-scian').textContent =
      '—';

    $('result-probability').textContent =
      'No concluyente';

  } else {

    $('result-activity').textContent =
      prediction.activity || '—';

    $('result-scian').textContent =
      prediction.scian || '—';

    $('result-probability').textContent =
      probabilityLabel(
        prediction.probability,
        2
      );
  }

  const hero =
    document.querySelector(
      '.prediction-result-hero'
    );

  if (hero) {

    hero.classList.toggle(
      'ambiguous-result',
      isAmbiguous
    );

    hero.classList.toggle(
      'accepted-result',
      !isAmbiguous
    );
  }
  const statusElement =
    $('result-confidence-status');

  if (statusElement) {

    if (isAmbiguous) {

      statusElement.className =
        'prediction-confidence-status ambiguous';

      statusElement.textContent =
        'Alta ambigüedad';

    } else {

      statusElement.className =
        'prediction-confidence-status accepted';

      statusElement.textContent =
        'Predicción suficientemente clara';
    }
  }
  const ambiguityMessage =
    $('result-ambiguity-message');

  if (ambiguityMessage) {

    if (isAmbiguous) {

      ambiguityMessage.classList.remove(
        'hidden'
      );

      ambiguityMessage.innerHTML = `
        <strong>
          El modelo se abstuvo de emitir una actividad definitiva.
        </strong>

        <span>
          La distribución de probabilidades no cumple
          los criterios de claridad establecidos mediante
          validación espacial. Consulta las tres alternativas
          principales.
        </span>
      `;

    } else {

      ambiguityMessage.classList.add(
        'hidden'
      );

      ambiguityMessage.innerHTML = '';
    }
  }
  $('result-lat').textContent =
    Number(
      result.lat
    ).toFixed(6);

  $('result-lon').textContent =
    Number(
      result.lon
    ).toFixed(6);

  $('result-nearby').textContent =
    fmt(
      result.nearby_units
    );

  $('result-dominant').textContent =
    result.dominant_activity ||
    'Sin actividad observada';


  if (result.cell) {

    $('result-cell').textContent =
      `${result.cell.x}, ${result.cell.y}`;

    $('result-cell-size').textContent =
  `${fmt(result.cell.size_m)} × ${fmt(result.cell.size_m)} m`;

    $('result-occupied').textContent =
      result.cell.occupied
        ? 'Sí'
        : 'No';

  } else {

    $('result-cell').textContent =
      '—';

    $('result-cell-size').textContent =
      '—';

    $('result-occupied').textContent =
      '—';
  }


  $('result-model-version').textContent =
    result.model_version || '—';

  const policyElement =
    $('result-policy-detail');

  if (
    policyElement &&
    ambiguity
  ) {

    const pSelected =
      probabilityLabel(
        ambiguity.p_selected,
        3
      );

    const entropy =
      Number(
        ambiguity.entropy_norm
      ).toFixed(3);

    policyElement.innerHTML = `
  <span>
    Probabilidad de clase seleccionada:
    <strong>${pSelected}</strong>
  </span>

  <span>
    Umbral mínimo:
    <strong>
      ${probabilityLabel(
        ambiguity.thresholds.p_selected_min,
        3
      )}
    </strong>
  </span>

  <span>
    Entropía normalizada:
    <strong>${entropy}</strong>
  </span>

  <span>
    Entropía máxima:
    <strong>
      ${Number(
        ambiguity.thresholds.entropy_max
      ).toFixed(3)}
    </strong>
  </span>
`;
  }

  const groupedNote =
    $('result-grouped-note');

  if (
    prediction.grouped &&
    !isAmbiguous
  ) {

    groupedNote.classList.remove(
      'hidden'
    );

    const ids =
      prediction.included_activity_ids ||
      [];

    $('result-grouped-text').textContent =
      ids.length
        ? `Esta salida agrupa las actividades ${ids.join(', ')} debido a su baja representación individual como clase predominante.`
        : 'Esta salida representa un conjunto de actividades con baja representación individual.';

  } else {

    groupedNote.classList.add(
      'hidden'
    );

    $('result-grouped-text').textContent =
      '';
  }

  const top3Container =
    $('prediction-top3');

  const top3 =
    Array.isArray(
      result.top3
    )
      ? result.top3
      : [];

  if (!top3.length) {

    top3Container.innerHTML = `
      <p class="muted">
        No se recibieron alternativas del modelo.
      </p>
    `;

    return;
  }


  top3Container.innerHTML =
    top3
      .map(
        (item, index) => {

          const probability =
            Number(
              item.probability || 0
            );

          const width =
            Math.max(
              0,
              Math.min(
                100,
                probability * 100
              )
            );

          const scian =
            item.scian
              ? `SCIAN ${escapeHtml(item.scian)}`
              : 'Clase agrupada';

          return `
            <article
              class="prediction-top3-item
              ${index === 0 ? 'top-result' : ''}"
            >

              <div class="prediction-top3-rank">
                ${index + 1}
              </div>

              <div class="prediction-top3-body">

                <div class="prediction-top3-head">

                  <div>

                    <strong>
                      ${escapeHtml(
                        item.activity ||
                        'Sin nombre'
                      )}
                    </strong>

                    <span>
                      ${scian}
                    </span>

                  </div>

                  <b>
                    ${probabilityLabel(
                      probability,
                      2
                    )}
                  </b>

                </div>

                <div class="prediction-probability-track">

                  <div
                    class="prediction-probability-fill"
                    style="width:${width}%"
                  ></div>

                </div>

              </div>

            </article>
          `;
        }
      )
      .join('');
}


async function runPrediction() {

  if (!selectedPredictionPoint) {
    return;
  }

  const button =
    $('predict-btn');

  button.disabled = true;

  button.textContent =
    'Analizando…';

  $('prediction-message').textContent =
    'Construyendo las 422 variables y ejecutando el modelo…';

  try {

    const result = await api(
      '/predicciones',
      {
        method:
          'POST',

        headers:
          {
            'Content-Type':
              'application/json',
          },

        body:
          JSON.stringify(
            {
              lat:
                selectedPredictionPoint.lat,

              lon:
                selectedPredictionPoint.lng,
            }
          ),
      }
    );


    $('pred-nearby').textContent =
      fmt(
        result.nearby_units
      );

    $('pred-dominant').textContent =
      result.dominant_activity ||
      'Sin actividad cercana';

    $('prediction-message').textContent =
      result.message;


    if (
      result.status !== 'ok' ||
      !result.prediction
    ) {

      clearPredictionResult();

      return;
    }


    lastPredictionResult =
  result;


if (
  result.cell
) {

  drawPredictionCell(
    result.cell
  );
}


renderPredictionResult(
  result
);

    setPredictionResultEnabled(
      true
    );

    switchView(
      'resultado-prediccion'
    );

  } catch (err) {

    clearPredictionResult();

    $('prediction-message').textContent =
      `Error: ${err.message}`;

  } finally {

    button.disabled =
      !selectedPredictionPoint;

    button.textContent =
      'Analizar punto seleccionado';
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
  'resultado-prediccion': 'Resultado de predicción',
  acerca: 'Acerca del sistema',
};
  const subtitles = {

  dashboard:
    'Panorama general de las unidades económicas registradas en la Ciudad de México.',

  alcaldia:
    'Análisis detallado de las unidades económicas de una alcaldía seleccionada.',

  detalle:
    'Información individual y contexto territorial de una unidad económica.',

  prediccion:
    'Selecciona una ubicación para analizar su entorno económico.',

  'resultado-prediccion':
    'Resultado generado por el modelo de actividad económica predominante.',

  acerca:
    'Información general, fuentes de datos y arquitectura del sistema.',
};

  $('page-title').textContent = labels[name];
  $('breadcrumb-current').textContent = labels[name];
  document.querySelector('.page-subtitle').textContent = subtitles[name];

  if (name === 'alcaldia') {
    if ($('filter-alcaldia').value) $('alcaldia-select').value = $('filter-alcaldia').value;
    loadAlcaldiaModule().catch(console.error);
  }
  if (name === 'acerca') {

  loadAboutSystem()
    .catch(console.error);
}

  setTimeout(() => {

  if (name === 'dashboard') {
    map.invalidateSize();
  }

  if (name === 'alcaldia') {
    alcaldiaMap.invalidateSize();
  }

  if (name === 'prediccion') {
    predictionMap.invalidateSize();
  }

  if (
    name === 'detalle' &&
    detailMap
  ) {

    detailMap.invalidateSize();
  }

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
$('detail-back').addEventListener(
  'click',
  () => {

    switchView(
      lastViewBeforeDetail ||
      'dashboard'
    );

  }
);


$('detail-empty-back').addEventListener(
  'click',
  () => {

    switchView(
      'dashboard'
    );

  }
);
$('predict-btn').addEventListener('click', runPrediction);
$('use-manual-coordinates').addEventListener(
  'click',
  useManualPredictionCoordinates
);


[
  'manual-pred-lat',
  'manual-pred-lon'
].forEach(
  id => {

    $(id).addEventListener(
      'keydown',
      event => {

        if (
          event.key === 'Enter'
        ) {

          event.preventDefault();

          useManualPredictionCoordinates();
        }
      }
    );
  }
);
$('prediction-new-point').addEventListener(
  'click',
  () => {

    switchView(
      'prediccion'
    );

    setTimeout(
      () => {

        predictionMap.invalidateSize();


        if (
          lastPredictionResult?.cell
        ) {

          drawPredictionCell(
            lastPredictionResult.cell,
            {
              fit: true
            }
          );
        }

      },
      100
    );
  }
);


$('prediction-result-back').addEventListener(
  'click',
  () => {

    switchView(
      'prediccion'
    );

    setTimeout(
      () => {

        predictionMap.invalidateSize();


        if (
          lastPredictionResult?.cell
        ) {

          drawPredictionCell(
            lastPredictionResult.cell,
            {
              fit: true
            }
          );
        }

      },
      100
    );
  }
);
initMaps();
bootstrap();
