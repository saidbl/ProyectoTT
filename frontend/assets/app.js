const API = '/api';
let map;
let unitLayer;
let alcaldiaLayer;
let predictionMap;
let predictionMarker;
let selectedPredictionPoint = null;

const $ = (id) => document.getElementById(id);
const fmt = (value) => new Intl.NumberFormat('es-MX').format(value || 0);

async function api(path, options) {
  const res = await fetch(`${API}${path}`, options);
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

function initMaps() {
  map = L.map('map', { zoomControl: true }).setView([19.4326, -99.1332], 10);
  predictionMap = L.map('prediction-map').setView([19.4326, -99.1332], 10);
  const tiles = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
  const attribution = '&copy; OpenStreetMap contributors';
  L.tileLayer(tiles, { attribution, maxZoom: 19 }).addTo(map);
  L.tileLayer(tiles, { attribution, maxZoom: 19 }).addTo(predictionMap);
  predictionMap.on('click', onPredictionClick);
}

async function bootstrap() {
  try {
    await api('/health');
    $('api-status').textContent = 'API: conectada';
    $('kpi-status').textContent = 'Operativo';
  } catch (err) {
    $('api-status').textContent = 'API: sin conexión';
    $('kpi-status').textContent = 'Sin conexión';
  }

  try {
    const [alcaldias, sectores] = await Promise.all([api('/alcaldias'), api('/sectores')]);
    alcaldias.forEach(a => $('filter-alcaldia').insertAdjacentHTML('beforeend', `<option value="${a.id}">${a.nombre}</option>`));
    sectores.forEach(s => $('filter-sector').insertAdjacentHTML('beforeend', `<option value="${s.id}">${s.nombre}</option>`));
    await Promise.all([loadDashboard(), loadAlcaldiasLayer()]);
  } catch (err) {
    console.error(err);
    renderEmptyState(err.message);
  }
}

function currentQuery() {
  const params = new URLSearchParams();
  if ($('filter-alcaldia').value) params.set('alcaldia_id', $('filter-alcaldia').value);
  if ($('filter-sector').value) params.set('sector_id', $('filter-sector').value);
  return params;
}

async function loadDashboard() {
  const params = currentQuery();
  const summary = await api(`/dashboard/resumen?${params}`);
  $('kpi-unidades').textContent = fmt(summary.total_unidades);
  const top = summary.top_actividades[0];
  $('kpi-actividad').textContent = top ? top.codigo_scian : '—';
  $('kpi-actividad-count').textContent = top ? `${top.descripcion} · ${fmt(top.unidades)}` : 'sin datos';
  const topSector = summary.distribucion_sector[0];
  $('kpi-sector').textContent = topSector ? topSector.nombre : '—';
  $('kpi-sector-count').textContent = topSector ? `${fmt(topSector.unidades)} unidades` : 'sin datos';
  renderBars('top-activities', summary.top_actividades, item => `${item.codigo_scian} · ${item.descripcion}`, 'unidades');
  renderBars('sector-bars', summary.distribucion_sector, item => item.nombre, 'unidades');
  renderBars('alcaldia-bars', summary.distribucion_alcaldia, item => item.nombre, 'unidades');
  await loadUnits();
}

function renderBars(containerId, items, labelFn, valueKey) {
  const el = $(containerId);
  if (!items.length) { el.innerHTML = '<p class="muted">No hay registros para los filtros seleccionados.</p>'; return; }
  const max = Math.max(...items.map(i => Number(i[valueKey]) || 0), 1);
  el.innerHTML = items.map(item => {
    const value = Number(item[valueKey]) || 0;
    const pct = Math.max((value / max) * 100, 2);
    return `<div class="bar-row"><span class="bar-label" title="${labelFn(item)}">${labelFn(item)}</span><strong>${fmt(value)}</strong><div class="bar-track"><div class="bar-fill" style="width:${pct}%"></div></div></div>`;
  }).join('');
}

async function loadAlcaldiasLayer() {
  const geo = await api('/alcaldias/geojson');
  if (alcaldiaLayer) alcaldiaLayer.remove();
  alcaldiaLayer = L.geoJSON(geo, {
    style: { color: '#5f56d8', weight: 1.2, fillOpacity: 0.04 },
    onEachFeature: (feature, layer) => layer.bindTooltip(feature.properties.nombre),
  }).addTo(map);
}

async function loadUnits() {
  const params = currentQuery();
  params.set('limit', $('filter-limit').value);
  const geo = await api(`/unidades?${params}`);
  if (unitLayer) unitLayer.remove();
  unitLayer = L.geoJSON(geo, {
    pointToLayer: (_feature, latlng) => L.circleMarker(latlng, { radius: 3, weight: 0.5, fillOpacity: .7 }),
    onEachFeature: (feature, layer) => {
      const p = feature.properties;
      layer.bindPopup(`<strong>${p.nombre || 'Unidad económica'}</strong><br>${p.codigo_scian || '—'} · ${p.actividad || 'Sin actividad'}<br><small>${p.alcaldia || ''}</small><br><button onclick="openUnit(${p.id})">Ver detalle</button>`);
    },
  }).addTo(map);
  if (geo.features.length && $('filter-alcaldia').value) {
    try { map.fitBounds(unitLayer.getBounds(), { padding: [20,20], maxZoom: 13 }); } catch (_) {}
  }
}

async function openUnit(id) {
  try {
    const u = await api(`/unidades/${id}`);
    $('unit-detail').innerHTML = `<h3>${u.nombre || 'Unidad económica'}</h3><p><strong>SCIAN:</strong> ${u.codigo_scian || '—'}<br><strong>Actividad:</strong> ${u.actividad || '—'}<br><strong>Sector:</strong> ${u.sector || '—'}<br><strong>Alcaldía:</strong> ${u.alcaldia || '—'}<br><strong>Coordenadas:</strong> ${u.lat}, ${u.lon}</p>`;
    switchView('detalle');
  } catch (err) { console.error(err); }
}
window.openUnit = openUnit;

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
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ lat: selectedPredictionPoint.lat, lon: selectedPredictionPoint.lng }),
    });
    $('pred-nearby').textContent = fmt(result.nearby_units);
    $('pred-dominant').textContent = result.dominant_activity || 'Sin actividad cercana';
    $('prediction-message').textContent = result.message;
  } catch (err) { $('prediction-message').textContent = `Error: ${err.message}`; }
}

function renderEmptyState(message) {
  ['top-activities','sector-bars','alcaldia-bars'].forEach(id => $(id).innerHTML = `<p class="muted">Sin datos. ${message}</p>`);
}

function switchView(name) {
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(v => v.classList.remove('active'));
  $(`view-${name}`).classList.add('active');
  document.querySelector(`.nav-item[data-view="${name}"]`).classList.add('active');
  const labels = { dashboard: 'Dashboard principal', alcaldia: 'Consulta por alcaldía', detalle: 'Detalle de unidad económica', prediccion: 'Módulo de predicción' };
  $('page-title').textContent = labels[name];
  setTimeout(() => { if (name === 'dashboard') map.invalidateSize(); if (name === 'prediccion') predictionMap.invalidateSize(); }, 30);
}

document.querySelectorAll('.nav-item').forEach(btn => btn.addEventListener('click', () => switchView(btn.dataset.view)));
$('apply-filters').addEventListener('click', loadDashboard);
$('predict-btn').addEventListener('click', runPrediction);

initMaps();
bootstrap();
