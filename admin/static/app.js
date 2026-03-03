/* Smart Home V2 Admin - UI */
const API = '/api';

function toast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.style.display = 'block';
  setTimeout(() => { el.style.display = 'none'; }, 2500);
}

async function fetchJSON(url, opts = {}) {
  const r = await fetch(url, { ...opts, headers: { 'Content-Type': 'application/json', ...opts.headers } });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

// Tabs
document.querySelectorAll('.tabs button').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tabs button').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('panel-' + btn.dataset.tab).classList.add('active');
  });
});

// --- Maison ---
let homeData = { rooms: {}, presets: { lighting: {}, global: {} }, sensor_types: {} };

function renderRooms() {
  const c = document.getElementById('rooms-container');
  c.innerHTML = '';
  for (const [name, room] of Object.entries(homeData.rooms || {})) {
    const div = document.createElement('div');
    div.className = 'room-item';
    div.innerHTML = `
      <input class="name" value="${escapeHtml(name)}" placeholder="nom pièce" data-room="${escapeHtml(name)}">
      <div class="lists">
        <div class="mb"><small class="text-muted">Lumières</small><br>
          <input value="${(room.lights || []).join(', ')}" placeholder="plafond, lampadaire" data-lights="${escapeHtml(name)}">
        </div>
        <div class="mb"><small class="text-muted">Appareils</small><br>
          <input value="${(room.devices || []).join(', ')}" placeholder="tele, enceinte" data-devices="${escapeHtml(name)}">
        </div>
        <div><small class="text-muted">Capteurs</small><br>
          <input value="${(room.sensors || []).join(', ')}" placeholder="temperature, humidite" data-sensors="${escapeHtml(name)}">
        </div>
        <button class="btn btn-danger btn-sm mt" data-remove="${escapeHtml(name)}">Suppr</button>
      </div>
    `;
    c.appendChild(div);
  }
  c.querySelectorAll('[data-remove]').forEach(b => {
    b.addEventListener('click', () => {
      delete homeData.rooms[b.dataset.remove];
      renderRooms();
    });
  });
  c.querySelectorAll('[data-lights]').forEach(inp => {
    inp.addEventListener('change', () => {
      const room = inp.dataset.lights;
      homeData.rooms[room] = homeData.rooms[room] || {};
      homeData.rooms[room].lights = inp.value.split(',').map(s => s.trim()).filter(Boolean);
    });
  });
  c.querySelectorAll('[data-devices]').forEach(inp => {
    inp.addEventListener('change', () => {
      const room = inp.dataset.devices;
      homeData.rooms[room] = homeData.rooms[room] || {};
      homeData.rooms[room].devices = inp.value.split(',').map(s => s.trim()).filter(Boolean);
    });
  });
  c.querySelectorAll('[data-sensors]').forEach(inp => {
    inp.addEventListener('change', () => {
      const room = inp.dataset.sensors;
      homeData.rooms[room] = homeData.rooms[room] || {};
      homeData.rooms[room].sensors = inp.value.split(',').map(s => s.trim()).filter(Boolean);
    });
  });
  c.querySelectorAll('.room-item').forEach(row => {
    const nameInp = row.querySelector('.name');
    const lightsInp = row.querySelector('[data-lights]');
    const devicesInp = row.querySelector('[data-devices]');
    const sensorsInp = row.querySelector('[data-sensors]');
    nameInp.addEventListener('blur', () => {
      const old = nameInp.dataset.room;
      const neu = nameInp.value.trim();
      if (neu && neu !== old) {
        const room = homeData.rooms[old] || {};
        room.lights = (lightsInp?.value || '').split(',').map(s => s.trim()).filter(Boolean);
        room.devices = (devicesInp?.value || '').split(',').map(s => s.trim()).filter(Boolean);
        room.sensors = (sensorsInp?.value || '').split(',').map(s => s.trim()).filter(Boolean);
        homeData.rooms[neu] = room;
        delete homeData.rooms[old];
        nameInp.dataset.room = neu;
        renderRooms();
      }
    });
  });
}

function escapeHtml(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

document.getElementById('add-room').addEventListener('click', () => {
  const name = prompt('Nom de la pièce ?');
  if (name && name.trim()) {
    homeData.rooms[name.trim()] = { lights: [], devices: [], sensors: [] };
    renderRooms();
  }
});

document.getElementById('save-home').addEventListener('click', async () => {
  homeData.house_name = document.getElementById('house-name').value || homeData.house_name;
  try {
    await fetch(API + '/home', { method: 'PUT', body: JSON.stringify(homeData) });
    toast('Maison enregistrée');
  } catch (e) { toast('Erreur: ' + e.message); }
});

// --- Alias ---
let aliasesData = { entries: {} };

function renderAliases() {
  const c = document.getElementById('aliases-container');
  c.innerHTML = '';
  for (const [key, entry] of Object.entries(aliasesData.entries || {})) {
    const div = document.createElement('div');
    div.className = 'alias-row';
    div.innerHTML = `
      <input placeholder="alias" value="${escapeHtml(key)}" data-key="${escapeHtml(key)}">
      <select data-type="${escapeHtml(key)}">
        <option value="room" ${entry.type === 'room' ? 'selected' : ''}>room</option>
        <option value="device" ${entry.type === 'device' ? 'selected' : ''}>device</option>
        <option value="fixture" ${entry.type === 'fixture' ? 'selected' : ''}>fixture</option>
        <option value="preset" ${entry.type === 'preset' ? 'selected' : ''}>preset</option>
      </select>
      <input placeholder="canonical" value="${escapeHtml(entry.canonical || '')}" data-can="${escapeHtml(key)}">
      <button class="btn btn-danger btn-sm" data-del="${escapeHtml(key)}">×</button>
    `;
    c.appendChild(div);
  }
  c.querySelectorAll('[data-del]').forEach(b => {
    b.addEventListener('click', () => {
      delete aliasesData.entries[b.dataset.del];
      renderAliases();
    });
  });
  c.querySelectorAll('.alias-row').forEach(row => {
    const keyInp = row.querySelector('[data-key]');
    const typeSel = row.querySelector('[data-type]');
    const canInp = row.querySelector('[data-can]');
    keyInp.addEventListener('blur', () => {
      const old = keyInp.dataset.key;
      const neu = keyInp.value.trim();
      if (neu && neu !== old) {
        const entry = { ...(aliasesData.entries[old] || {}), type: typeSel?.value || 'device', canonical: canInp?.value?.trim() || '' };
        aliasesData.entries[neu] = entry;
        delete aliasesData.entries[old];
        renderAliases();
      }
    });
  });
  c.querySelectorAll('[data-type]').forEach(sel => {
    sel.addEventListener('change', () => {
      aliasesData.entries[sel.dataset.type] = aliasesData.entries[sel.dataset.type] || {};
      aliasesData.entries[sel.dataset.type].type = sel.value;
    });
  });
  c.querySelectorAll('[data-can]').forEach(inp => {
    inp.addEventListener('change', () => {
      aliasesData.entries[inp.dataset.can] = aliasesData.entries[inp.dataset.can] || {};
      aliasesData.entries[inp.dataset.can].canonical = inp.value.trim();
    });
  });
}

document.getElementById('add-alias').addEventListener('click', () => {
  const key = prompt('Alias (ex: tv) ?');
  if (key && key.trim()) {
    aliasesData.entries[key.trim()] = { type: 'device', canonical: '' };
    renderAliases();
  }
});

document.getElementById('save-aliases').addEventListener('click', async () => {
  try {
    await fetch(API + '/aliases', { method: 'PUT', body: JSON.stringify(aliasesData) });
    toast('Alias enregistrés');
  } catch (e) { toast('Erreur: ' + e.message); }
});

// --- Tools ---
document.getElementById('save-tools').addEventListener('click', async () => {
  try {
    const data = JSON.parse(document.getElementById('tools-json').value);
    await fetch(API + '/tools', { method: 'PUT', body: JSON.stringify(data) });
    toast('Tools enregistrés');
  } catch (e) { toast('Erreur JSON: ' + e.message); }
});

// --- Prompt ---
document.getElementById('save-prompt').addEventListener('click', async () => {
  try {
    await fetch(API + '/prompt', { method: 'PUT', body: JSON.stringify({ content: document.getElementById('prompt-text').value }) });
    toast('Prompt enregistré');
  } catch (e) { toast('Erreur: ' + e.message); }
});

// --- Presets ---
function renderPresets() {
  const lit = homeData.presets?.lighting || {};
  const glo = homeData.presets?.global || {};
  const c1 = document.getElementById('presets-lighting');
  const c2 = document.getElementById('presets-global');
  c1.innerHTML = '';
  c2.innerHTML = '';
  for (const [n] of Object.entries(lit)) {
    c1.innerHTML += `<div class="preset-item"><span class="name">${escapeHtml(n)}</span><br><span class="scope">lighting</span><br><button class="btn btn-primary btn-sm" data-edit-lit="${escapeHtml(n)}">Éditer</button> <button class="btn btn-danger btn-sm" data-del-lit="${escapeHtml(n)}">Suppr</button></div>`;
  }
  for (const [n] of Object.entries(glo)) {
    c2.innerHTML += `<div class="preset-item"><span class="name">${escapeHtml(n)}</span><br><span class="scope">global</span><br><button class="btn btn-primary btn-sm" data-edit-glo="${escapeHtml(n)}">Éditer</button> <button class="btn btn-danger btn-sm" data-del-glo="${escapeHtml(n)}">Suppr</button></div>`;
  }
  c1.querySelectorAll('[data-edit-lit]').forEach(b => {
    b.addEventListener('click', () => openPresetEditor('lighting', b.dataset.editLit));
  });
  c2.querySelectorAll('[data-edit-glo]').forEach(b => {
    b.addEventListener('click', () => openPresetEditor('global', b.dataset.editGlo));
  });
  c1.querySelectorAll('[data-del-lit]').forEach(b => {
    b.addEventListener('click', async () => {
      if (!confirm('Supprimer ce preset ?')) return;
      const name = b.dataset.delLit;
      delete homeData.presets.lighting[name];
      try {
        await fetch(API + `/presets/lighting/${encodeURIComponent(name)}`, { method: 'DELETE' });
      } catch (_) {}
      renderPresets();
    });
  });
  c2.querySelectorAll('[data-del-glo]').forEach(b => {
    b.addEventListener('click', async () => {
      if (!confirm('Supprimer ce preset ?')) return;
      const name = b.dataset.delGlo;
      delete homeData.presets.global[name];
      try {
        await fetch(API + `/presets/global/${encodeURIComponent(name)}`, { method: 'DELETE' });
      } catch (_) {}
      renderPresets();
    });
  });
}

let presetEditScope = null, presetEditName = null;

function openPresetEditor(scope, name) {
  presetEditScope = scope;
  presetEditName = name;
  const file = `${scope}_${name}.json`;
  document.getElementById('preset-modal-title').textContent = `Éditer ${file}`;
  document.getElementById('preset-modal-file').textContent = `knowledge/presets/${file}`;
  document.getElementById('preset-modal-hint').innerHTML = `Contenu de <code>${file}</code> → paramètres pour les tools (ex: intensity, color_temp, color)`;
  document.getElementById('preset-modal-json').value = '{}';
  document.getElementById('preset-modal').style.display = 'flex';
  fetchJSON(API + `/presets/${scope}/${name}/content`).then(r => {
    document.getElementById('preset-modal-json').value = JSON.stringify(r.content || {}, null, 2);
  }).catch(() => {});
}

function closePresetEditor() {
  document.getElementById('preset-modal').style.display = 'none';
  presetEditScope = null;
  presetEditName = null;
}

document.getElementById('preset-modal-close').addEventListener('click', closePresetEditor);
document.getElementById('preset-modal-cancel').addEventListener('click', closePresetEditor);
document.getElementById('preset-modal').addEventListener('click', (e) => {
  if (e.target.id === 'preset-modal') closePresetEditor();
});

document.getElementById('preset-modal-save').addEventListener('click', async () => {
  if (!presetEditScope || !presetEditName) return;
  try {
    const raw = document.getElementById('preset-modal-json').value.trim();
    const content = raw ? JSON.parse(raw) : {};
    await fetch(API + `/presets/${presetEditScope}/${presetEditName}/content`, {
      method: 'PUT',
      body: JSON.stringify({ content })
    });
    toast('Preset enregistré');
    closePresetEditor();
  } catch (e) {
    toast('Erreur JSON: ' + e.message);
  }
});

document.getElementById('add-preset-lighting').addEventListener('click', () => {
  const n = prompt('Nom preset lighting ?');
  if (n && n.trim()) {
    homeData.presets.lighting[n.trim()] = {};
    renderPresets();
  }
});

document.getElementById('add-preset-global').addEventListener('click', () => {
  const n = prompt('Nom preset global ?');
  if (n && n.trim()) {
    homeData.presets.global[n.trim()] = {};
    renderPresets();
  }
});

document.getElementById('save-presets').addEventListener('click', async () => {
  try {
    await fetch(API + '/home', { method: 'PUT', body: JSON.stringify(homeData) });
    toast('Presets enregistrés');
  } catch (e) { toast('Erreur: ' + e.message); }
});

document.getElementById('import-preset').addEventListener('click', () => document.getElementById('preset-file').click());
document.getElementById('preset-file').addEventListener('change', async (e) => {
  const f = e.target.files[0];
  if (!f) return;
  const form = new FormData();
  form.append('file', f);
  try {
    const r = await fetch(API + '/presets/import', { method: 'POST', body: form });
    const j = await r.json();
    if (!r.ok) throw new Error(j.detail || 'Erreur');
    toast('Importé: ' + j.name);
    homeData = await fetchJSON(API + '/home');
    renderPresets();
  } catch (err) { toast('Erreur: ' + err.message); }
  e.target.value = '';
});

// --- Config (modèle) ---
document.getElementById('save-config').addEventListener('click', async () => {
  try {
    await fetch(API + '/config', {
      method: 'PUT',
      body: JSON.stringify({
        model_id: document.getElementById('config-model').value,
        model_path: document.getElementById('config-model-path').value.trim(),
        llama_port: parseInt(document.getElementById('config-llama-port').value, 10) || 8085,
        llama_base_url: document.getElementById('config-llama-url').value.trim()
      })
    });
    toast('Paramètres enregistrés');
  } catch (e) { toast('Erreur: ' + e.message); }
});

// Load all
async function load() {
  try {
    [homeData, aliasesData] = await Promise.all([
      fetchJSON(API + '/home'),
      fetchJSON(API + '/aliases')
    ]);
    document.getElementById('house-name').value = homeData.house_name || '';
    renderRooms();
    renderAliases();
    renderPresets();

    const tools = await fetchJSON(API + '/tools');
    document.getElementById('tools-json').value = JSON.stringify(tools, null, 2);

    const prompt = await fetchJSON(API + '/prompt');
    document.getElementById('prompt-text').value = prompt.content || '';

    const config = await fetchJSON(API + '/config');
    const sel = document.getElementById('config-model');
    sel.innerHTML = '';
    for (const m of config.models_in_dir || []) {
      sel.innerHTML += `<option value="${escapeHtml(m.id)}">${escapeHtml(m.file)} (dossier models/)</option>`;
    }
    for (const m of config.available_models || []) {
      sel.innerHTML += `<option value="${escapeHtml(m.id)}">${escapeHtml(m.file)} (${m.size})</option>`;
    }
    sel.value = config.model_id || 'Qwen3.5-2B-Q6_K';
    document.getElementById('config-model-path').value = config.model_path || '';
    document.getElementById('config-llama-url').value = config.llama_base_url || 'http://127.0.0.1:8085';
    document.getElementById('config-llama-port').value = config.llama_port || 8085;
  } catch (e) {
    toast('Erreur chargement: ' + e.message);
  }
}

load();
