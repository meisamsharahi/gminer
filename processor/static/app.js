'use strict';
const $ = s => document.querySelector(s);
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const paths = {
  spark:'M12 2l2.8 7.2L22 12l-7.2 2.8L12 22l-2.8-7.2L2 12l7.2-2.8L12 2z',
  grid:'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',
  folder:'M3 7V5a1 1 0 011-1h5l2 3h9a1 1 0 011 1v11H3V7z',
  settings:'M9 3h6l1 4 4 1v8l-4 1-1 4H9l-1-4-4-1V8l4-1 1-4z M15 12a3 3 0 11-6 0 3 3 0 016 0z',
  plus:'M12 5v14 M5 12h14', arrow:'M5 12h14 M14 7l5 5-5 5',
  file:'M5 3h9l5 5v13H5V3z M14 3v6h5 M8 13h8 M8 17h5',
  check:'M5 12l4 4L19 6', close:'M6 6l12 12 M6 18L18 6',
  scan:'M8 3H3v5 M16 3h5v5 M3 16v5h5 M21 16v5h-5 M7 12h10',
  play:'M8 4l12 8-12 8V4z', pause:'M8 5v14 M16 5v14',
  refresh:'M20 8a8 8 0 10.1 7 M20 3v5h-5', search:'M10 17a7 7 0 110-14 7 7 0 010 14z M15 15l6 6',
  chevron:'M9 5l7 7-7 7', lock:'M6 10h12v11H6V10z M8 10V6a4 4 0 018 0v4',
  clock:'M12 22a10 10 0 110-20 10 10 0 010 20z M12 6v6l4 2',
  coin:'M12 22a10 10 0 110-20 10 10 0 010 20z M15 8h-4a2 2 0 000 4h2a2 2 0 010 4H9 M12 6v12',
  edit:'M14 5l5 5 M3 21l5-1L21 7l-5-5L3 15v6z',
  info:'M12 22a10 10 0 110-20 10 10 0 010 20z M12 11v6 M12 7h.01',
  logout:'M9 3H3v18h6 M10 12h11 M16 7l5 5-5 5', download:'M12 3v12 M7 10l5 5 5-5 M4 17v4h16v-4',
  list:'M9 6h12 M9 12h12 M9 18h12 M3 6h.01 M3 12h.01 M3 18h.01',
  trash:'M3 6h18 M9 6V3h6v3 M5 6l1 15h12l1-15 M10 10v7 M14 10v7'
};
const icon = (name, extra='') => `<svg viewBox="0 0 24 24" aria-hidden="true" class="${extra}"><path d="${paths[name] || paths.file}"/></svg>`;
const labels = {draft:'Not scanned',ready:'Ready',running:'Running',warming:'Warming up',pausing:'Pausing',paused:'Paused',completed:'Completed',pending:'Pending',processing:'Processing',golden:'Golden',not_selected:'Not selected',needs_review:'Needs review',error:'Failed',interrupted:'Interrupted',export_error:'Export failed',met:'Met',not_met:'Not met',unknown:'Uncertain'};
const badge = value => `<span class="badge ${esc(value)}">${value==='golden' ? icon('spark') : ''}${esc(labels[value] || value)}</span>`;
const money = value => value == null ? 'Unknown' : `$${value.toFixed(value < .01 && value > 0 ? 5 : 3)}`;
const number = value => value == null ? '—' : value.toLocaleString();
const bytes = value => value < 1024*1024 ? `${Math.round(value/1024)} KB` : `${(value/1024/1024).toFixed(1)} MB`;
const btn = (text, action, kind='', ico='', attrs='') => `<button class="btn ${kind}" data-action="${action}" ${attrs}>${ico ? icon(ico) : ''}${text}</button>`;
let state = {connections:[], conditions:[], profiles:[], files:[], attempts:[]};
let authenticated = false, settingTab = 'connections', fileSearch = '', fileFilter = 'all', toastTimer, reportData, reportAttempt;
let folderData = null, folderTarget = '', folderRequest = 0;
const busy = new Set();
const route = () => (location.hash.slice(1) || 'dashboard');
const profileFiles = id => state.files.filter(f => f.profile_id===id && f.present!==false);
const currentAttempt = file => state.attempts.find(a => a.id===file.last_attempt_id);
const working = p => ['running','warming','pausing'].includes(p.state);
const connection = p => state.connections.find(c => c.id===p.connection_id);
const conditionsCount = p => p.condition_ids.reduce((n,id) => n+(state.conditions.find(c=>c.id===id)?.criteria.length || 0),0);

async function api(path, options={}) {
  const response = await fetch('/api'+path, {headers:{'Content-Type':'application/json'}, ...options});
  let data;
  try { data = await response.json(); } catch { throw Error('The server returned an unreadable response. Please try again.'); }
  if (!response.ok) {
    if (response.status===401 && path!=='/login') { authenticated=false; $('#folder-picker').close(); $('#editor').close(); $('#report').close(); render(); }
    const detail = Array.isArray(data.detail) ? data.detail.map(e => `${e.loc.at(-1)}: ${e.msg}`).join('. ') : data.detail;
    throw Error(detail || 'Something went wrong. Please try again.');
  }
  return data;
}
function toast(message, error=false) {
  clearTimeout(toastTimer); $('#toast').textContent=message; $('#toast').className='show'+(error?' error':'');
  toastTimer=setTimeout(()=>$('#toast').className='',error?8500:4500);
}
async function refresh(renderView=true) {
  const next=await api('/state');
  const changed=JSON.stringify(next)!==JSON.stringify(state);
  state=next; authenticated=true;
  if(renderView && changed) render();
}

function shell(content, title) {
  const page=route().split('/')[0];
  return `<div class="shell"><aside class="sidebar"><a class="brand" href="#dashboard"><span class="brand-mark">${icon('spark')}</span>golden<span class="muted">.</span></a><div class="nav-label">WORKSPACE</div><nav class="nav" aria-label="Main navigation">
    <a href="#dashboard" class="${page==='dashboard'?'active':''}">${icon('grid')}Overview</a>
    <a href="#profiles" class="${page==='profiles'||page==='profile'?'active':''}">${icon('folder')}Scan profiles<span class="nav-count">${state.profiles.length}</span></a>
    <a href="#settings" class="${page==='settings'?'active':''}">${icon('settings')}Settings</a>
  </nav><div class="side-bottom"><div class="local-indicator"><span class="dot"></span>Local workspace</div><p class="side-note">Your folders. Your conditions.<br>A little more clarity.</p></div></aside>
  <main class="main"><header class="topbar"><div class="breadcrumb">Workspace ${icon('chevron')}<span>${esc(title)}</span></div><div class="top-actions"><a class="icon-button" href="#settings" aria-label="Settings">${icon('settings')}</a><span class="avatar" title="Administrator">AD</span><button class="icon-button" data-action="logout" aria-label="Sign out">${icon('logout')}</button></div></header><div class="content">${content}</div></main></div>`;
}
function stats(files=state.files.filter(f=>f.present!==false), attempts=state.attempts) {
  const finished=files.filter(f=>['golden','not_selected','needs_review','export_error','error','interrupted'].includes(f.status)).length;
  const golden=files.filter(f=>['golden','export_error'].includes(f.status)&&currentAttempt(f)?.status==='golden').length;
  const known=attempts.filter(a=>a.cost!=null), unknown=attempts.some(a=>a.cost==null && a.status!=='processing');
  const total=known.reduce((n,a)=>n+a.cost,0);
  return `<div class="stats"><div class="stat"><div class="stat-label">Files discovered ${icon('file')}</div><div class="stat-value">${number(files.length)}</div><div class="stat-foot">PDF, JPG & PNG documents</div></div>
  <div class="stat"><div class="stat-label">Files processed ${icon('check')}</div><div class="stat-value">${number(finished)}</div><div class="stat-foot">${files.length ? Math.round(finished/files.length*100) : 0}% of discovered files</div></div>
  <div class="stat gold"><div class="stat-label">Golden files ${icon('spark')}</div><div class="stat-value">${number(golden)}</div><div class="stat-foot">Above your acceptance threshold</div></div>
  <div class="stat"><div class="stat-label">Estimated API cost ${icon('coin')}</div><div class="stat-value">${attempts.length&&!known.length ? 'Unknown' : money(total)}</div><div class="stat-foot">${unknown ? 'Partial total · some usage is unknown' : 'USD · all processing attempts'}</div></div></div>`;
}
function emptyIllustration() { return `<div class="empty-illustration" aria-hidden="true"><div class="paper-icon"><span></span><span></span><span></span></div><div class="scan-frame">${icon('scan')}</div><span class="gold-spark">✦</span></div>`; }
function setupPanel() {
  const steps=[{done:state.connections.some(c=>c.tested),title:'Connect your LLM',text:'Choose a provider and verify your connection.',action:'go-connections'},
    {done:state.conditions.length>0,title:'Define what matters',text:'Write your conditions in your own words.',action:'go-conditions'},
    {done:state.profiles.length>0,title:'Create a scan profile',text:'Add your folders and set a golden threshold.',action:'new-profile'}];
  return `<aside><div class="panel setup"><div class="eyebrow">A SIMPLE START</div><h2>A few steps to your<br>first golden file.</h2><p>Set up once. Let your profiles do the rest.</p><div class="setup-progress"><span style="width:${steps.filter(s=>s.done).length/3*100}%"></span></div>${steps.map((s,i)=>`<div class="setup-step ${s.done?'done':''}"><div class="step-number">${s.done?icon('check'):i+1}</div><a href="#" data-action="${s.action}"><h3>${s.title}</h3><p>${s.text}</p></a></div>`).join('')}</div>
  <div class="note-card">${icon('spark')}<div><h3>What makes a file golden?</h3><p>A file is golden when its conditions met exceed your profile’s threshold. Uncertain answers are set aside for review.</p></div></div></aside>`;
}
function profileActions(p) {
  const files=profileFiles(p.id), pending=files.some(f=>f.status==='pending'), previous=files.some(f=>f.last_attempt_id);
  const ready=p.warmed_at && pending && connection(p)?.tested;
  const canRerun=p.warmed_at&&files.length&&connection(p)?.tested&&!working(p)&&!busy.has(p.id);
  const rerunButton=kind=>btn('Rerun','rerun',kind,'refresh',`data-id="${p.id}" ${canRerun?'':'disabled'} title="Evaluate all current files again using the latest profile settings"`);
  return `${btn(busy.has(p.id)?'Scanning…':'Warm up','warm','small','scan',`data-id="${p.id}" ${working(p)||busy.has(p.id)?'disabled':''} title="Discover supported files without contacting an LLM"`)}
    ${p.state==='running' ? btn('Pause','pause','small','pause',`data-id="${p.id}"`) : !pending&&previous ? rerunButton('small primary') : btn(p.state==='paused'?'Resume':'Start','start','small primary','play',`data-id="${p.id}" ${!ready||working(p)?'disabled':''} title="${!p.warmed_at?'Warm up first':!connection(p)?.tested?'Verify the LLM connection in Settings':!pending?'No pending files':'Process pending files'}"`)}
    ${pending&&previous&&!working(p)?rerunButton('small'):''}
    ${btn('View files','view-profile','small ghost','list',`data-id="${p.id}" ${!p.warmed_at?'disabled':''}`)}
    ${btn('Delete','delete','small danger-ghost','trash',`data-kind="profiles" data-id="${p.id}" ${working(p)||busy.has(p.id)?'disabled':''} aria-label="Delete scan profile ${esc(p.name)}"`)}`;
}
function profileCard(p) {
  const files=profileFiles(p.id), done=files.filter(f=>f.status!=='pending'&&f.status!=='processing').length;
  return `<article class="profile-card"><div class="profile-card-top"><div class="folder-icon">${icon('folder')}</div><div style="flex:1"><h2>${esc(p.name)}</h2><div class="model">${esc(connection(p)?.model || 'No model')}</div></div>${badge(p.state)}<button class="icon-button" data-action="edit-profile" data-id="${p.id}" ${working(p)?'disabled':''} aria-label="Edit ${esc(p.name)}">${icon('edit')}</button></div><div class="profile-folder" title="${esc(p.input_folder)}">${icon('folder')}<span>${esc(p.input_folder)}</span></div><div class="profile-card-meta"><span>${files.length} files</span><span>${conditionsCount(p)} conditions</span><span>Above ${p.threshold}% to qualify</span></div>${files.length?`<div class="progress-track"><span style="width:${done/files.length*100}%"></span></div>`:''}<div class="profile-card-actions">${profileActions(p)}</div></article>`;
}
function dashboard() {
  return shell(`<div class="page-heading"><div><div class="eyebrow" style="margin-bottom:10px">LESS SEARCHING. MORE CERTAINTY.</div><h1>Your document workspace.</h1><p>Turn a folder of documents into a shortlist that matters.</p></div>${btn('New scan profile','new-profile','primary','plus')}</div>${stats()}<div class="dashboard-grid"><section class="panel"><div class="panel-head"><div><h2>Scan profiles <span class="muted">${state.profiles.length?`· ${state.profiles.length}`:''}</span></h2><p class="help">Your folders, connected to your criteria.</p></div>${state.profiles.length?'<a class="text-button" href="#profiles">View all profiles →</a>':''}</div>${state.profiles.length?`<div class="profile-list">${state.profiles.slice(0,4).map(profileCard).join('')}</div>`:`<div class="empty-state">${emptyIllustration()}<h2>Good files are worth finding.</h2><p>Create your first scan profile. Choose a folder, add your conditions, and let your LLM find the matches.</p>${btn('Create your first profile','new-profile','primary','plus')}<span class="help" style="margin-top:13px;font-size:10px">Warm up is free. Processing starts only when you say so.</span></div>`}</section>${setupPanel()}</div><div class="bottom-note">${icon('lock')}Original files stay in place. Golden files are copied to your output folder.</div>`, 'Overview');
}
function profilesPage() {
  return shell(`<div class="page-heading"><div><h1>Scan profiles</h1><p>A focused workflow for every folder.</p></div>${btn('New scan profile','new-profile','primary','plus')}</div>${state.profiles.length?`<div class="profile-grid">${state.profiles.map(profileCard).join('')}</div>`:`<div class="panel empty-state">${emptyIllustration()}<h2>Your first profile starts here.</h2><p>Connect a folder, a model, and your conditions in one place.</p>${btn('Create scan profile','new-profile','primary','plus')}</div>`}`, 'Scan profiles');
}
function settingsPage() {
  const isLLM=settingTab==='connections', list=state[settingTab];
  return shell(`<div class="page-heading"><div><h1>Settings</h1><p>A little setup. A more useful workspace.</p></div></div><div class="tabs" role="tablist" aria-label="Settings section"><button class="tab ${isLLM?'active':''}" role="tab" aria-selected="${isLLM}" data-action="tab-connections">LLM connections</button><button class="tab ${!isLLM?'active':''}" role="tab" aria-selected="${!isLLM}" data-action="tab-conditions">Condition profiles</button></div><div class="section-tools"><div><h2>${isLLM?'Your LLM connections':'Your condition profiles'}</h2><p class="help" style="margin-top:6px">${isLLM?'Choose the models that power your scan profiles.':'Reusable criteria, written in everyday language.'}</p></div>${btn(isLLM?'Add connection':'Add conditions',isLLM?'new-connection':'new-condition','primary','plus')}</div>${isLLM?`<div class="notice">${icon('lock')}<span>API keys are encrypted on this computer. Connection tests check access to the model without sending a document. Enter model pricing to enable cost estimates.</span></div>`:`<div class="notice">${icon('info')}<span>Each line is one condition with equal weight. If you attach several condition profiles, their individual conditions are combined for scoring.</span></div>`}<div class="settings-list">${list.length ? list.map(value=>isLLM?connectionRow(value):conditionRow(value)).join('') : `<div class="panel empty-state">${emptyIllustration()}<h2>${isLLM?'Meet your document assistant.':'Tell us what to look for.'}</h2><p>${isLLM?'Connect OpenAI, Claude, Gemini, or a local Ollama model to get started.':'Give your criteria a name, then describe each condition in plain language.'}</p>${btn(isLLM?'Add your first connection':'Create condition profile',isLLM?'new-connection':'new-condition','primary','plus')}</div>`}</div>`, 'Settings');
}
function connectionRow(c) {return `<div class="panel setting-row"><div class="provider-icon">${esc({openai:'O',claude:'C',gemini:'G',ollama:'L'}[c.provider])}</div><div class="setting-main"><h3>${esc(c.name)}</h3><p>${esc(c.model)} · ${esc(c.provider==='ollama'?'Local Ollama':c.provider)} · ${c.input_rate==null||c.output_rate==null?'Pricing not set':'Pricing configured'}</p></div><span class="badge ${c.tested?'met':'needs_review'}">${c.tested?'Connected':'Test required'}</span><div class="button-row">${btn(busy.has(c.id)?'Testing…':'Test connection','test-connection','small','refresh',`data-id="${c.id}" ${busy.has(c.id)?'disabled':''}`)}${btn('Edit','edit-connection','small ghost','edit',`data-id="${c.id}"`)}${btn('Delete','delete','small danger-ghost','trash',`data-kind="connections" data-id="${c.id}" ${busy.has(c.id)?'disabled':''} aria-label="Delete LLM connection ${esc(c.name)}"`)}</div></div>`;}
function conditionRow(c) {return `<div class="panel setting-row"><div class="provider-icon">${icon('list')}</div><div class="setting-main"><h3>${esc(c.name)}</h3><p>${c.criteria.length} conditions · ${esc(c.criteria[0]?.text || '')}</p></div><div class="button-row">${btn('Edit','edit-condition','small','edit',`data-id="${c.id}"`)}${btn('Delete','delete','small danger-ghost','trash',`data-kind="conditions" data-id="${c.id}" aria-label="Delete condition profile ${esc(c.name)}"`)}</div></div>`;}
function profilePage(id) {
  const p=state.profiles.find(p=>p.id===id);
  if(!p) return shell('<div class="empty-state"><h2>Profile not found.</h2><a href="#profiles">Return to profiles</a></div>', 'Scan profiles');
  const files=profileFiles(id), attempts=state.attempts.filter(a=>a.profile_id===id);
  return shell(`<div class="page-heading"><div><a href="#profiles" class="help">← Scan profiles</a><h1 style="margin-top:12px">${esc(p.name)}</h1><p>${badge(p.state)} <span style="margin-left:8px">${files.length} documents in this workspace</span></p></div>${btn('Edit profile','edit-profile','','edit',`data-id="${id}" ${working(p)?'disabled':''}`)}</div>${stats(files,attempts)}<div class="panel profile-config"><div class="config-item"><div class="eyebrow">INPUT FOLDER</div><p>${esc(p.input_folder)}</p></div><div class="config-item"><div class="eyebrow">OUTPUT FOLDER</div><p>${esc(p.output_folder)}</p></div><div class="config-item"><div class="eyebrow">GOLDEN RULE</div><p>More than ${p.threshold}% of ${conditionsCount(p)} conditions</p><small>${esc(connection(p)?.model)}</small></div></div><div class="section-tools"><div><h2>Document queue</h2><p class="help" style="margin-top:6px">${p.warmed_at?'Last warm up: '+new Date(p.warmed_at).toLocaleString():'Warm up to discover your files. No LLM calls are made.'}</p></div><div class="button-row">${profileActions(p)}</div></div>${p.notice?`<div class="notice">${icon('info')}<span>${esc(p.notice)}</span></div>`:''}<section class="panel"><div class="table-tools"><div class="search">${icon('search')}<input id="file-search" aria-label="Search files" placeholder="Search files…" value="${esc(fileSearch)}"></div><select id="file-filter" class="filter" aria-label="Filter file status">${['all','pending','processing','golden','not_selected','needs_review','error','interrupted','export_error'].map(v=>`<option value="${v}" ${fileFilter===v?'selected':''}>${v==='all'?'All statuses':labels[v]}</option>`).join('')}</select></div><div class="table-scroll"><table><thead><tr><th>Document</th><th>Status</th><th>Model used</th><th>Tokens in / out</th><th>Est. cost</th><th>Match</th><th>Report</th></tr></thead><tbody id="file-rows">${fileRows(id)}</tbody></table></div><div class="table-foot"><span>${files.length} files · ${files.filter(f=>f.status==='pending').length} pending</span><span>USD estimates · provider-reported token counts</span></div></section>`, 'Scan profiles');
}
function fileRows(id) {
  const p=state.profiles.find(p=>p.id===id);
  const files=profileFiles(id).filter(f=>f.relative_path.toLowerCase().includes(fileSearch.toLowerCase())&&(fileFilter==='all'||fileFilter===f.status));
  return files.length?files.map(f=>{
    const a=currentAttempt(f);
    return `<tr><td><div class="file-name">${icon('file')}<div>${esc(f.name)}<small>${bytes(f.size)}${f.relative_path!==f.name?' · '+esc(f.relative_path):''}</small></div></div>${f.error?`<div class="file-error">${esc(f.error)}</div>`:''}</td><td>${badge(f.status)}</td><td>${a?esc(a.model):'—'}${a?`<div class="help" style="font-size:9px">${esc(a.provider)}</div>`:''}</td><td>${a?`${number(a.input_tokens)} / ${number(a.output_tokens)}`:'—'}</td><td>${a?money(a.cost):'—'}</td><td>${a?.score!=null?a.score.toFixed(1)+'%':'—'}</td><td>${a?`<button class="text-button" data-action="report" data-id="${f.id}">View report</button>`:'<span class="muted">Pending</span>'}${['error','interrupted','export_error'].includes(f.status)?`<div style="margin-top:9px"><button class="text-button" data-action="retry" data-id="${f.id}" ${working(p)?'disabled':''}>${f.status==='export_error'?'Retry export':'Queue retry'}</button></div>`:''}</td></tr>`;
  }).join(''):`<tr><td colspan="7" class="empty-table">${profileFiles(id).length?'No files match these filters.':'Your file list will appear here after warm up.'}</td></tr>`;
}
function loginPage() {
  return `<main class="login-screen"><section class="login-story"><div class="brand"><span class="brand-mark">${icon('spark')}</span>golden.</div><div class="login-story-main"><div class="eyebrow">YOUR DOCUMENTS, WITH DIRECTION</div><h1>A folder full<br>of files.<br><em>A few worth<br>finding.</em></h1><p>Your conditions. Your chosen model.<br>A clearer way to find the documents that matter.</p></div><div class="login-story-foot">A local workspace for thoughtful document screening.</div><div class="login-ring" aria-hidden="true"></div></section><section class="login-form-side"><form class="login-form" id="login-form"><div class="eyebrow" style="margin-bottom:15px">WELCOME TO GOLDEN</div><h2>Make yourself at home.</h2><p>Sign in to your document workspace.</p><div id="login-error" class="error-box" role="alert"></div><label class="field"><span class="field-label">Username</span><input name="username" autocomplete="username" placeholder="Enter your username" required autofocus></label><label class="field"><span class="field-label">Password</span><input name="password" type="password" autocomplete="current-password" placeholder="Enter your password" required></label><button class="btn primary" type="submit">Sign in ${icon('arrow')}</button><p class="login-note">${icon('lock')} Your workspace runs on this computer.</p></form></section></main>`;
}
function render() {
  const active=document.activeElement, selection=active?.id==='file-search'?active.selectionStart:null;
  if(!authenticated) { $('#app').innerHTML=loginPage(); return; }
  const page=route();
  $('#app').innerHTML=page.startsWith('profile/')?profilePage(page.split('/')[1]):page==='profiles'?profilesPage():page==='settings'?settingsPage():dashboard();
  if(selection!=null&&$('#file-search')) {$('#file-search').focus();$('#file-search').setSelectionRange(selection,selection);}
}

function field(label,name,value='',help='',type='text',attrs='') { return `<label class="field"><span class="field-label">${label}</span><input name="${name}" type="${type}" value="${esc(value)}" ${attrs}>${help?`<span class="help">${help}</span>`:''}</label>`; }
function folderField(label,name,value,help,placeholder) {
  return `<div class="field"><label class="field-label" for="folder-${name}">${label}</label><div class="folder-input-row"><input id="folder-${name}" name="${name}" value="${esc(value)}" required placeholder="${placeholder}" aria-describedby="help-${name}"><button type="button" class="btn" data-action="browse-folder" data-target="${name}" aria-label="Browse for ${label.toLowerCase()}">${icon('folder')}Browse</button></div><span class="help" id="help-${name}">${help}</span></div>`;
}

function renderFolderPicker() {
  const data=folderData, output=folderTarget==='output_folder';
  $('#folder-picker').innerHTML=`<div class="dialog-head"><div><h2 id="folder-picker-title">Choose ${output?'output':'input'} folder</h2><p>Browse folders on this computer. ${output?'You can also create a new output folder.':'Select the folder containing your documents.'}</p></div><button type="button" class="icon-button" data-action="close-folders" aria-label="Close folder browser">${icon('close')}</button></div><div class="dialog-body"><div id="folder-error" class="error-box" role="alert"></div>${data?`<div class="folder-shortcuts" aria-label="Folder shortcuts">${data.shortcuts.map(s=>`<button type="button" class="btn" data-action="navigate-folder" data-path="${esc(s.path)}">${icon('folder')}${esc(s.name)}</button>`).join('')}</div><form id="folder-location-form" class="folder-location"><label class="field"><span class="field-label">Current folder</span><input name="path" value="${esc(data.path)}" required aria-label="Folder location"></label><button class="btn" type="submit">Go</button></form><nav class="folder-breadcrumbs" aria-label="Folder path">${data.breadcrumbs.map((b,i)=>`${i?icon('chevron'):''}<button type="button" class="text-button" data-action="navigate-folder" data-path="${esc(b.path)}">${esc(b.name)}</button>`).join('')}</nav><div class="folder-toolbar"><button type="button" class="btn small" data-action="navigate-folder" data-path="${esc(data.parent||'')}" ${data.parent?'':'disabled'}>↑ Up one level</button>${output?'<button type="button" class="btn small" data-action="new-folder">'+icon('plus')+'New folder</button>':''}</div>${output?`<form id="new-folder-form" class="new-folder-form" hidden><div class="new-folder-row"><label class="field"><span class="field-label">New folder name</span><input name="name" required maxlength="255" autocomplete="off" placeholder="e.g. Golden results"></label><button class="btn" type="submit">Create</button><button class="icon-button" type="button" data-action="cancel-new-folder" aria-label="Cancel new folder">${icon('close')}</button></div></form>`:''}<div class="folder-list" aria-label="Subfolders">${data.folders.length?data.folders.map(f=>`<button type="button" class="folder-list-item" data-action="navigate-folder" data-path="${esc(f.path)}">${icon('folder')}<span>${esc(f.name)}</span>${icon('chevron')}</button>`).join(''):'<div class="folder-empty">No subfolders here.<br>You can select this folder.</div>'}</div>${data.truncated?'<p class="help">Showing the first 1,000 subfolders. Use the folder location field to open another path.</p>':''}<p class="folder-selection">Selected folder:<br><strong>${esc(data.path)}</strong></p>`:'<div class="folder-empty">Loading folders…</div>'}</div><div class="dialog-footer"><button type="button" class="btn" data-action="close-folders">Cancel</button><button type="button" class="btn primary" data-action="select-folder" ${data?'':'disabled'}>${icon('check')}Select this folder</button></div>`;
}

async function navigateFolder(path) {
  const request=++folderRequest;
  const errorBox=$('#folder-error');if(errorBox)errorBox.textContent='';
  const selectButton=$('#folder-picker [data-action="select-folder"]');if(selectButton)selectButton.disabled=true;
  try {
    const data=await api('/folders'+(path?'?path='+encodeURIComponent(path):''));
    if(request!==folderRequest||!$('#folder-picker').open)return;
    folderData=data;renderFolderPicker();
  } catch(error) {
    if(request===folderRequest&&$('#folder-picker').open)$('#folder-error').textContent=error.message;
    throw error;
  } finally {
    if(request===folderRequest){const button=$('#folder-picker [data-action="select-folder"]');if(button)button.disabled=!folderData;}
  }
}

async function browseFolder(target) {
  const input=$('#edit-form')?.elements[target];if(!input)return;
  folderTarget=target;folderData=null;renderFolderPicker();$('#folder-picker').showModal();
  try {await navigateFolder(input.value.trim());}
  catch(error) {
    if(!$('#folder-picker').open)return;
    // A not-yet-created output path should still open a usable browser.
    if(input.value.trim())try{await navigateFolder('');$('#folder-error').textContent='Could not open the entered path. Choose a folder below, or create an output folder.';}catch{}
  }
}
function openEditor(title,subtitle,form,kind,id='') {
  $('#editor').innerHTML=`<form id="edit-form" data-kind="${kind}" data-id="${id}"><div class="dialog-head"><div><h2 id="dialog-title">${title}</h2><p>${subtitle}</p></div><button type="button" class="icon-button" data-action="close-editor" aria-label="Close">${icon('close')}</button></div><div class="dialog-body"><div id="form-error" class="error-box" role="alert"></div>${form}</div><div class="dialog-footer"><button type="button" class="btn" data-action="close-editor">Cancel</button><button class="btn primary" type="submit">${id?'Save changes':'Create '+({connections:'connection',conditions:'conditions',profiles:'profile'}[kind])}${icon('arrow')}</button></div></form>`;
  $('#editor').showModal();
}
function editConnection(id) {
  const c=state.connections.find(c=>c.id===id)||{provider:'openai'};
  openEditor(id?'Edit connection':'Connect an LLM','Choose a provider and the exact model you want to use.',`<div class="form-grid">${field('Connection name','name',c.name||'','','text','required maxlength="100" placeholder="e.g. Primary reviewer"')}<label class="field"><span class="field-label">Provider</span><select name="provider" id="provider-select">${[['openai','OpenAI / ChatGPT'],['claude','Anthropic / Claude'],['gemini','Google / Gemini'],['ollama','Local / Ollama']].map(([v,t])=>`<option value="${v}" ${c.provider===v?'selected':''}>${t}</option>`).join('')}</select></label></div>${field('Model ID','model',c.model||'','Use the model ID available to your API account. For images, choose a vision-capable model.','text','required placeholder="Enter model ID" maxlength="150"')}${field('API key','api_key','','Saved keys stay hidden. Leave blank to keep the current key.','password',`autocomplete="new-password" placeholder="${c.has_key?'Key saved · leave blank to keep':'Paste your API key'}"`)}${field('Server address','base_url',c.base_url||'','Leave blank to use the provider’s default. For Ollama: http://localhost:11434.','url','placeholder="Use provider default"')}<div class="form-section"><div class="eyebrow">OPTIONAL · COST ESTIMATES</div><div class="form-grid">${field('Input · USD per 1M tokens','input_rate',c.input_rate??'','','number','min="0" step="any" placeholder="Not set"')}${field('Output · USD per 1M tokens','output_rate',c.output_rate??'','','number','min="0" step="any" placeholder="Not set"')}</div><p class="help">Enter your model’s current rates. Estimates use standard token rates; caching and tiered pricing can change the final bill. Local Ollama has no provider API charge.</p></div>`,'connections',id);
}
function editCondition(id) {
  const c=state.conditions.find(c=>c.id===id)||{};
  openEditor(id?'Edit condition profile':'What makes a document a match?','Write one clear condition per line. Each line counts equally.',`${field('Profile name','name',c.name||'','','text','required maxlength="100" placeholder="e.g. Oil and gas leases"')}<label class="field"><span class="field-label">Conditions</span><textarea name="conditions" required placeholder="The document grants oil or gas extraction rights.&#10;The property is located in Belmont County.&#10;The document contains a signed agreement.">${esc(c.criteria?.map(v=>v.text).join('\n')||'')}</textarea><span class="help">Describe what must be true. The LLM will report met, not met, or uncertain for every condition, with supporting evidence.</span></label>`,'conditions',id);
}
function editProfile(id) {
  if(!state.connections.length||!state.conditions.length) {
    settingTab=!state.connections.length?'connections':'conditions';location.hash='settings';render();
    toast(!state.connections.length?'First, add an LLM connection. Then define your conditions.':'Create a condition profile before adding a scan profile.');
    return;
  }
  const p=state.profiles.find(p=>p.id===id)||{threshold:70,condition_ids:[]};
  openEditor(id?'Edit scan profile':'Create a scan profile','One folder, one model, and a clear definition of golden.',`<div class="form-section"><div class="eyebrow">01 · THE BASICS</div>${field('Profile name','name',p.name||'','','text','required maxlength="100" placeholder="e.g. Belmont lease review"')}<div class="form-grid">${folderField('Input folder','input_folder',p.input_folder||'','Browse to an existing folder. Subfolders are included.','/Users/you/Documents/input')}${folderField('Output folder','output_folder',p.output_folder||'','Choose or create a folder for golden files and reports.','/Users/you/Documents/selected')}</div></div><div class="form-section"><div class="eyebrow">02 · THE INTELLIGENCE</div><label class="field"><span class="field-label">LLM connection</span><select name="connection_id" required>${state.connections.map(c=>`<option value="${c.id}" ${p.connection_id===c.id?'selected':''}>${esc(c.name)} · ${esc(c.model)}${c.tested?'':' (test required)'}</option>`).join('')}</select></label><div class="field"><span class="field-label">Condition profiles</span><div class="checks">${state.conditions.map(c=>`<label class="check-row"><input type="checkbox" name="condition_ids" value="${c.id}" ${p.condition_ids.includes(c.id)?'checked':''}>${esc(c.name)}<small>${c.criteria.length} conditions</small></label>`).join('')}</div><span class="help">Choose one or more. Every individual condition has equal weight.</span></div></div><div class="form-section"><div class="eyebrow">03 · THE GOLDEN RULE</div><label class="field"><span class="field-label">Acceptance threshold</span><div class="range-row"><input name="threshold" id="threshold-range" type="range" min="0" max="99" step="1" value="${p.threshold}"><output id="threshold-output" class="range-value">${p.threshold}%</output></div><span class="help">More than <strong id="threshold-inline">${p.threshold}%</strong> of conditions must be met. For example, 7 out of 10 does not exceed 70%; 8 out of 10 does. Any uncertain result goes to review.</span></label></div>`,'profiles',id);
}
async function showReport(id) {
  reportData=await api(`/files/${id}/report`);
  reportAttempt=reportData.attempts.at(-1)?.id;
  renderReport(); $('#report').showModal();
}
function renderReport() {
  const f=reportData.file, attempts=reportData.attempts, a=attempts.find(a=>a.id===reportAttempt);
  $('#report').innerHTML=`<div class="dialog-head"><div><div class="eyebrow" style="margin-bottom:9px">DOCUMENT REPORT</div><h2 id="report-title">${esc(f.name)}</h2><p>${bytes(f.size)} · ${a?.pages||'?'} pages ${a?.image_pages?' · '+a.image_pages+' image pages':''}</p></div><button class="icon-button" data-action="close-report" aria-label="Close report">${icon('close')}</button></div><div class="dialog-body">${attempts.length>1?`<label class="field report-history"><span class="field-label">Processing history</span><select id="attempt-select">${[...attempts].reverse().map((v,i)=>`<option value="${v.id}" ${v.id===a?.id?'selected':''}>${new Date(v.created_at).toLocaleString()} · ${esc(v.connection.model)} · ${labels[v.status]||v.status}</option>`).join('')}</select></label>`:''}${a?`<div class="section-tools">${badge(a.status)}<span class="help">${a.score!=null?a.score.toFixed(1)+'% matched · ':''}above ${a.threshold}% required</span></div>${a.error?`<div class="error-box">${esc(a.error)}</div>`:''}${f.status==='export_error'?`<div class="error-box">${esc(f.error)}</div>`:''}<div class="stats report-stats"><div class="stat"><div class="stat-label">Input tokens</div><div class="stat-value">${number(a.input_tokens)}</div></div><div class="stat"><div class="stat-label">Output tokens</div><div class="stat-value">${number(a.output_tokens)}</div></div><div class="stat"><div class="stat-label">Est. API cost</div><div class="stat-value">${money(a.cost)}</div></div></div><p class="help">${esc(a.connection.name)} · ${esc(a.connection.provider)} / ${esc(a.connection.model)}<br>${a.duration??'—'} seconds · ${new Date(a.created_at).toLocaleString()}<br>Cost is an estimate using the rates saved for this attempt.</p>${a.result?.summary?`<div class="report-summary" style="margin-top:20px">${esc(a.result.summary)}</div>`:''}<h3 class="report-section-title">Condition-by-condition findings</h3><div class="report-criteria">${a.criteria.map(c=>{const r=a.result?.conditions.find(r=>r.id===c.id);return `<article class="criterion"><div class="criterion-head"><h3>${esc(c.text)}</h3>${r?badge(r.result):'<span class="badge">Not evaluated</span>'}</div><p>${esc(r?.explanation||'No valid finding was returned for this condition.')}</p>${r?.evidence?`<div class="evidence">${esc(r.evidence)}${r.pages?.length?`<br>Pages ${r.pages.join(', ')}`:''}</div>`:''}<p class="help" style="margin-top:10px;font-size:9px">${esc(c.group)}</p></article>`;}).join('')}</div>${a.copied_to?`<div class="notice" style="margin-top:20px">${icon('check')}<span>Golden copy saved to<br>${esc(a.copied_to)}</span></div>`:''}${a.raw_response?`<details><summary>Original LLM response</summary><pre class="raw">${esc(a.raw_response)}</pre></details>`:''}<div style="margin-top:25px"><a class="btn" href="/api/files/${f.id}/report/download" download>${icon('download')}Download complete report</a></div>`:'<p class="help">Processing has not started.</p>'}</div>`;
}

document.addEventListener('click',async event=>{
  const target=event.target.closest('[data-action]');if(!target)return;
  event.preventDefault();const action=target.dataset.action,id=target.dataset.id;
  try {
    if(action==='browse-folder')return await browseFolder(target.dataset.target);
    if(action==='close-folders'){folderRequest++;return $('#folder-picker').close();}
    if(action==='navigate-folder'){try{await navigateFolder(target.dataset.path);}catch{}return;}
    if(action==='select-folder'){
      const input=$('#edit-form')?.elements[folderTarget];
      if(input&&folderData){input.value=folderData.path;input.dispatchEvent(new Event('change',{bubbles:true}));}
      folderRequest++;$('#folder-picker').close();input?.focus();return;
    }
    if(action==='new-folder'){$('#new-folder-form').hidden=false;$('#new-folder-form input').focus();return;}
    if(action==='cancel-new-folder'){$('#new-folder-form').hidden=true;return;}
    if(action==='close-editor')return $('#editor').close();
    if(action==='close-report')return $('#report').close();
    if(action==='logout'){await api('/logout',{method:'POST'});authenticated=false;return render();}
    if(action==='new-profile'||action==='edit-profile')return editProfile(id);
    if(action==='new-connection'||action==='edit-connection')return editConnection(id);
    if(action==='new-condition'||action==='edit-condition')return editCondition(id);
    if(action==='go-connections'||action==='go-conditions'){settingTab=action==='go-connections'?'connections':'conditions';location.hash='settings';return render();}
    if(action.startsWith('tab-')){settingTab=action.slice(4);return render();}
    if(action==='view-profile'){fileSearch='';fileFilter='all';location.hash=`profile/${id}`;return;}
    if(action==='report')return await showReport(id);
    if(action==='rerun')return openRerun(id);
    if(action==='delete')return openDelete(target.dataset.kind,id);
    if(action==='test-connection'){
      if(busy.has(id))return;busy.add(id);render();
      try{const result=await api(`/connections/${id}/test`,{method:'POST'});toast(result.message);}
      finally{busy.delete(id);await refresh(false);render();}return;
    }
    if(['warm','start','pause'].includes(action)){
      if(busy.has(id))return;busy.add(id);render();
      try{await api(`/profiles/${id}/${action}`,{method:'POST'});toast({warm:'Folder scanned. Your file list is ready.',start:'Processing started. You can leave this page open or continue working.',pause:'Pause requested. The current file will finish first.'}[action]);}
      finally{busy.delete(id);await refresh(false);render();}return;
    }
    if(action==='retry'){
      const file=state.files.find(f=>f.id===id);
      if(file.status!=='export_error')return openRetry(id);
      await api(`/files/${id}/retry`,{method:'POST'});await refresh();toast('Export retried. No LLM request was made.');
    }
  }catch(error){toast(error.message,true);}
});
function openRetry(id){
  $('#editor').innerHTML=`<form id="retry-form" data-id="${id}"><div class="dialog-head"><div><h2 id="dialog-title">Queue another attempt?</h2><p>The next Start or Resume will send this file to the LLM again.</p></div><button type="button" class="icon-button" data-action="close-editor" aria-label="Close">${icon('close')}</button></div><div class="dialog-body"><div id="form-error" class="error-box" role="alert"></div><p class="help">A previous request may already have incurred charges. Its history and reported usage will be kept.</p></div><div class="dialog-footer"><button type="button" class="btn" data-action="close-editor">Cancel</button><button class="btn primary" type="submit">Queue retry</button></div></form>`;
  $('#editor').showModal();
}
function openRerun(id){
  const p=state.profiles.find(p=>p.id===id);if(!p||working(p))return;
  const count=profileFiles(id).length;
  $('#editor').innerHTML=`<form id="rerun-form" data-id="${id}"><div class="dialog-head"><div><h2 id="dialog-title">Rerun ${esc(p.name)}?</h2><p>Evaluate all ${count} file${count===1?'':'s'} again using your current settings.</p></div><button type="button" class="icon-button" data-action="close-editor" aria-label="Close">${icon('close')}</button></div><div class="dialog-body"><div id="form-error" class="error-box" role="alert"></div><div class="notice">${icon('refresh')}<span>${esc(connection(p)?.model)}<br>${conditionsCount(p)} condition${conditionsCount(p)===1?'':'s'} · more than ${p.threshold}% required</span></div><p class="help">Previous reports, usage history, and output copies will be kept. Rerunning sends new LLM requests and may incur additional charges.</p><p class="help" style="margin-top:12px">This uses your latest file list. Run Warm up first if you have added or changed files.</p></div><div class="dialog-footer"><button type="button" class="btn" data-action="close-editor">Cancel</button><button class="btn primary" type="submit">${icon('refresh')}Rerun all files</button></div></form>`;
  $('#editor').showModal();
}
function openDelete(kind,id){
  const names={connections:'LLM connection',conditions:'condition profile',profiles:'scan profile'};
  if(!names[kind])return;
  const item=state[kind].find(value=>value.id===id);if(!item)return;
  const references=kind==='profiles'?[]:state.profiles.filter(p=>kind==='connections'?p.connection_id===id:p.condition_ids.includes(id));
  const active=kind==='profiles'&&working(item),blocked=active||references.length>0;
  const files=state.files.filter(f=>f.profile_id===id).length,attempts=state.attempts.filter(a=>a.profile_id===id).length;
  const explanation=kind==='profiles'
    ? `This removes the scan profile, ${files} file record${files===1?'':'s'}, and ${attempts} processing attempt${attempts===1?'':'s'} from the app. Your original files, exported reports, and golden copies stay on disk.`
    : kind==='connections'
    ? 'This removes the connection and its saved API key. Existing processing reports keep their original model details.'
    : 'This removes the reusable condition profile. Existing processing reports keep the conditions used for their evaluation.';
  const restriction=active?'Pause this profile and wait for its current work to finish before deleting it.'
    : references.length?`This ${names[kind]} is used by: ${references.map(p=>p.name).join(', ')}. Edit or delete those scan profiles first.`:'';
  $('#editor').innerHTML=`<form id="delete-form" data-kind="${kind}" data-id="${id}"><div class="dialog-head"><div><h2 id="dialog-title">Delete ${names[kind]}?</h2><p>${esc(item.name)}</p></div><button type="button" class="icon-button" data-action="close-editor" aria-label="Close">${icon('close')}</button></div><div class="dialog-body"><div id="form-error" class="error-box" role="alert">${esc(restriction)}</div><p class="help">${explanation}</p>${blocked?'':'<p class="delete-warning">This cannot be undone.</p>'}</div><div class="dialog-footer"><button type="button" class="btn" data-action="close-editor" autofocus>${blocked?'Close':'Cancel'}</button><button class="btn primary danger" type="submit" ${blocked?'disabled':''}>${icon('trash')}Delete ${names[kind]}</button></div></form>`;
  $('#editor').showModal();
}
document.addEventListener('submit',async event=>{
  event.preventDefault();const form=event.target, button=form.querySelector('[type=submit]');if(!button)return;
  button.disabled=true;
  const values=Object.fromEntries(new FormData(form));
  try{
    if(form.id==='folder-location-form'){
      try{await navigateFolder(values.path.trim());}catch{}return;
    }
    if(form.id==='new-folder-form'){
      $('#folder-error').textContent='';
      const created=await api('/folders',{method:'POST',body:JSON.stringify({parent:folderData.path,name:values.name})});
      await navigateFolder(created.path);return;
    }
    if(form.id==='login-form'){
      $('#login-error').textContent='';await api('/login',{method:'POST',body:JSON.stringify(values)});await refresh(false);render();return;
    }
    if(form.id==='delete-form'){
      const kind=form.dataset.kind,id=form.dataset.id;if(busy.has(id))return;
      $('#form-error').textContent='';busy.add(id);
      try{
        await api(`/${kind}/${id}`,{method:'DELETE'});
        $('#editor').close();await refresh(false);
        if(kind==='profiles'&&route()===`profile/${id}`)location.hash='profiles';
        render();toast('Deleted successfully.');
      }finally{busy.delete(id);}
      return;
    }
    if(form.id==='retry-form'){
      await api(`/files/${form.dataset.id}/retry`,{method:'POST'});$('#editor').close();await refresh();toast('File queued. Start or resume its profile to process it.');return;
    }
    if(form.id==='rerun-form'){
      const id=form.dataset.id;if(busy.has(id))return;
      $('#form-error').textContent='';busy.add(id);
      try{
        await api(`/profiles/${id}/rerun`,{method:'POST'});
        $('#editor').close();await refresh(false);render();toast('Rerun started using the current profile settings. Previous reports are kept.');
      }finally{busy.delete(id);}
      return;
    }
    if(form.id==='edit-form'){
      $('#form-error').textContent='';const kind=form.dataset.kind,id=form.dataset.id;
      if(kind==='connections'){values.input_rate=values.input_rate===''?null:Number(values.input_rate);values.output_rate=values.output_rate===''?null:Number(values.output_rate);}
      if(kind==='conditions')values.conditions=values.conditions.split('\n').map(v=>v.trim()).filter(Boolean);
      if(kind==='profiles'){values.condition_ids=new FormData(form).getAll('condition_ids');values.threshold=Number(values.threshold);if(!values.condition_ids.length)throw Error('Choose at least one condition profile.');}
      const saved=await api(`/${kind}${id?'/'+id:''}`,{method:id?'PUT':'POST',body:JSON.stringify(values)});
      $('#editor').close();await refresh(false);
      if(kind==='profiles')location.hash=`profile/${saved.id}`;
      render();toast(kind==='connections'?'Connection saved. Test it to enable processing.':'Saved successfully.');
    }
  }catch(error){const box=form.id==='new-folder-form'?$('#folder-error'):form.querySelector('.error-box');if(box)box.textContent=error.message;else toast(error.message,true);}
  finally{button.disabled=false;}
});
document.addEventListener('input',event=>{
  if(event.target.id==='threshold-range'){$('#threshold-output').textContent=event.target.value+'%';$('#threshold-inline').textContent=event.target.value+'%';}
  if(event.target.id==='file-search'){fileSearch=event.target.value;$('#file-rows').innerHTML=fileRows(route().split('/')[1]);}
});
document.addEventListener('change',event=>{
  if(event.target.id==='file-filter'){fileFilter=event.target.value;$('#file-rows').innerHTML=fileRows(route().split('/')[1]);}
  if(event.target.id==='attempt-select'){reportAttempt=event.target.value;renderReport();}
  if(event.target.id==='provider-select'){
    const form=event.target.form;form.elements.base_url.value='';form.elements.api_key.value='';
    form.elements.api_key.required=event.target.value!=='ollama'&&!state.connections.find(c=>c.id===form.dataset.id)?.has_key;
  }
});
window.addEventListener('hashchange',()=>{fileSearch='';fileFilter='all';render();});
async function boot(){
  $('#app').innerHTML='<div class="loading">Opening your workspace…</div>';
  try{await refresh(false);render();}catch(error){render();if(!error.message.includes('sign in'))toast(error.message,true);}
}
boot();
setInterval(async()=>{if(!authenticated||document.hidden)return;try{await refresh(true);}catch(error){if(authenticated)toast('Connection to workspace lost. Retrying…',true);}},3000);
