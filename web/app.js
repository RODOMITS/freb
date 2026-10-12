import { SETTINGS, ITEMS, ITEM_BY_ID, CASES, CASE_BY_ID, RARITIES } from './config.js';
import { distribution, rollCase, randomUnit, upgradeChance, buildUpgradeStake, liquidLevel, upgradeLanding, settleSlots, newState, validateState, recordOperation, createPromo, redeemPromo, togglePromo, adjustBalance, startMines, revealMine, cashMines } from './engine.js';
import { SoundEngine } from './audio.js';
import { renderMines, renderHistory, renderAdmin, renderRocket, rocketGeometry } from './feature-views.js';
import { startRocket, advanceRocket, cashRocket, rocketValue, rocketFinished, rollSlots } from './engine.js';
import { connectServer, sharedRocket, verifyProof } from './server-client.js';

const server = await connectServer();
if (server?.catalog) {
  ITEMS.splice(0,ITEMS.length,...server.catalog.items);
  Object.keys(ITEM_BY_ID).forEach(id=>delete ITEM_BY_ID[id]); Object.assign(ITEM_BY_ID,Object.fromEntries(ITEMS.map(i=>[i.id,i])));
  CASES.splice(0,CASES.length,...server.catalog.cases);
  Object.keys(CASE_BY_ID).forEach(id=>delete CASE_BY_ID[id]); Object.assign(CASE_BY_ID,Object.fromEntries(CASES.map(c=>[c.id,c])));
}

const $ = (selector) => document.querySelector(selector);
const money = n => new Intl.NumberFormat('ru-RU').format(n);
const percent = n => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 }).format(n * 100) + '%';
const esc = text => String(text).replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
const icons = {
  box: '<path d="m3 7 9-5 9 5v10l-9 5-9-5Z"/><path d="m3 7 9 5 9-5M12 12v10M7.5 4.5l9 5"/>',
  upgrade: '<path d="m5 12 7-8 7 8M12 4v16M4 20h16"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 21v-2a8 8 0 0 1 16 0v2"/>',
  gift: '<path d="M3 9h18v4H3zM5 13v8h14v-8M12 9v12"/><path d="M12 9S5 9 5 5a3 3 0 0 1 6-1l1 5Zm0 0s7 0 7-4a3 3 0 0 0-6-1l-1 5Z"/>',
  arrow: '<path d="m14 6-6 6 6 6M8 12h13"/>',
  shield: '<path d="m12 2 8 4v6c0 5-8 10-8 10S4 17 4 12V6Z"/><path d="m8 12 3 3 5-6"/>',
  bolt: '<path d="m13 2-9 12h7l-1 8 10-13h-7Z"/>',
  search: '<circle cx="10" cy="10" r="7"/><path d="m15 15 6 6"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  withdraw: '<path d="M4 4h16v16H4zM12 16V8m-4 4 4-4 4 4"/>',
  sound: '<path d="M3 9v6h4l5 4V5L7 9Z"/><path d="M16 8a6 6 0 0 1 0 8M19 5a10 10 0 0 1 0 14"/>',
  muted: '<path d="M3 9v6h4l5 4V5L7 9Z"/><path d="m17 9 5 6m0-6-5 6"/>',
  slots: '<rect x="3" y="4" width="18" height="16" rx="4"/><path d="M9 7v10M15 7v10M5 12h2m4 0h2m4 0h2"/>',
  mines: '<circle cx="11" cy="14" r="7"/><path d="m15 8 2-3h3M18 2v2m3 1 2-1M8 12l2-2"/>',
  gem: '<path d="m3 9 4-5h10l4 5-9 12ZM3 9h18M7 4l5 17 5-17"/>',
  rocket: '<path d="M14 4c3-1 6-1 6-1s0 3-1 6l-7 7-5-5ZM7 11l-4 1v6l4-2m5 0-2 5h6l1-4M4 20l3-3"/><circle cx="15" cy="8" r="2"/>',
};
const icon = name => `<svg viewBox="0 0 24 24" aria-hidden="true">${icons[name] || icons.box}</svg>`;
document.querySelectorAll('[data-icon]').forEach(el => el.innerHTML = icon(el.dataset.icon));

let storageWorks = true;
let state;
try { state = validateState(JSON.parse(localStorage.getItem(SETTINGS.storageKey))); } catch { state = newState(); storageWorks = false; }
if (server) state=server.state || {...newState(),balance:0,inventory:[]};
let busy = false, activeRoute = '', sourceUids = new Set(), targetId = null, quick = null, targetSearch = '', toastTimer;
let displayedChance = 0, gaugeFrame = 0;
let fastMode = false, slotUid = null;
let mineUids = new Set(), mineCount = 5, historyFilter = 'all', historyLimit = 20;
let rocketUids=new Set(), rocketAuto=false, rocketAutoTarget=2, rocketFrame=0, rocketCompletedId=null;
try { const prefs=JSON.parse(localStorage.getItem('brainrot-freebie-rocket')); if (prefs && Number.isFinite(prefs.target) && prefs.target>=1.01 && prefs.target<=100) { rocketAuto=!!prefs.enabled; rocketAutoTarget=prefs.target; } } catch {}
if (state.rocket && !rocketFinished(state.rocket)) { rocketAuto=state.rocket.autoCash!==null; rocketAutoTarget=state.rocket.autoCash || rocketAutoTarget; }
const featureUI = {esc,money,icon,itemCard,inventoryEmpty,server:!!server,now:server?.now};
try { fastMode = localStorage.getItem('brainrot-freebie-fast') === 'on'; } catch {}
function fastButton() {
  return `<button class="fast-toggle" data-action="fast" aria-label="Быстрый режим" title="Быстрый режим" aria-pressed="${fastMode}">${icon('bolt')}</button>`;
}
let soundEnabled = true;
try { soundEnabled = localStorage.getItem('brainrot-freebie-sound') !== 'off'; } catch {}
const sound = new SoundEngine({ enabled:soundEnabled });
function updateSoundButton() {
  $('#sound-toggle').innerHTML = icon(sound.enabled ? 'sound' : 'muted');
  $('#sound-toggle').setAttribute('aria-pressed', String(sound.enabled));
  $('#sound-toggle').setAttribute('aria-label', sound.enabled ? 'Выключить звук' : 'Включить звук');
}
updateSoundButton();
// Resume from a real gesture (including keyboard activation), before async spins.
document.addEventListener('pointerdown', () => sound.unlock(), {passive:true});
document.addEventListener('keydown', () => sound.unlock());
const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
const tg = window.Telegram?.WebApp;
const telegramUser = server?.state?.profile || tg?.initDataUnsafe?.user;
const playerName = telegramUser?.username ? `@${telegramUser.username}` : telegramUser?.first_name || 'Miami Player';
const isTelegram = Boolean(tg?.initData);

function haptic(type = 'light') { try { if (isTelegram) tg.HapticFeedback?.impactOccurred(type); } catch { /* Older client. */ } }
function notifyHaptic(success) { try { if (isTelegram) tg.HapticFeedback?.notificationOccurred(success ? 'success' : 'error'); } catch { /* Older client. */ } }
function syncSafeAreas() {
  if (!isTelegram) return;
  const area = tg.contentSafeAreaInset;
  const safe = tg.safeAreaInset;
  document.documentElement.style.setProperty('--safe-top', `${Math.max(area?.top || 0, safe?.top || 0)}px`);
  document.documentElement.style.setProperty('--safe-bottom', `${Math.max(area?.bottom || 0, safe?.bottom || 0)}px`);
}
if (isTelegram) {
  try {
    tg.ready(); tg.expand(); tg.setHeaderColor('#100f1b'); tg.setBackgroundColor('#100f1b');
    if (tg.isVersionAtLeast('7.10')) tg.setBottomBarColor('#100f1b');
    tg.BackButton.onClick(() => { if ($('#modal').open) closeModal(); else if (!busy) location.hash = 'cases'; });
    tg.onEvent('safeAreaChanged', syncSafeAreas); tg.onEvent('contentSafeAreaChanged', syncSafeAreas); syncSafeAreas();
  } catch (error) { console.info('Telegram client compatibility:', error.message); }
}

function persist({ balanceVisible = true } = {}) {
  if (!server) { try { localStorage.setItem(SETTINGS.storageKey, JSON.stringify(state)); } catch { storageWorks = false; toast('Сохранение недоступно: прогресс останется до перезагрузки.'); } }
  if (balanceVisible) $('#balance').textContent = money(state.balance);
}
function toast(message) {
  $('#toast').textContent = message; $('#toast').classList.add('visible');
  clearTimeout(toastTimer); toastTimer = setTimeout(() => $('#toast').classList.remove('visible'), 3400);
}
function setBusy(value) {
  busy = value;
  $('.bottom-nav').classList.toggle('busy', value);
  $('#main').setAttribute('aria-busy', String(value));
  $('.balance').disabled = value;
  document.querySelectorAll('.fast-toggle').forEach(button => button.disabled = value);
  if (isTelegram) { try { value ? tg.enableClosingConfirmation() : tg.disableClosingConfirmation(); } catch {} }
}
function openModal(html) { $('#modal-body').innerHTML = html; if (!$('#modal').open) $('#modal').showModal(); }
function closeModal() { $('#modal').close(); }
$('#modal').addEventListener('click', event => { if (event.target === $('#modal')) { const r = $('#modal').getBoundingClientRect(); if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) closeModal(); } });

function itemCard(item, options = {}) {
  const { action, id = item.id, selected = false, chance, sale = false, eager = false } = options;
  const tag = action ? 'button' : 'div';
  return `<${tag} class="item-card ${item.rarity} ${action ? 'selectable' : ''} ${selected ? 'selected' : ''}" ${action ? `data-action="${action}" data-id="${esc(id)}" aria-label="${esc(item.name)}, ${money(item.value)} BStars${sale ? ', продать' : ''}" ${action.startsWith('select-') ? `aria-pressed="${selected}"` : ''}` : ''}>
    ${selected ? '<span class="selected-check">✓</span>' : ''}${chance !== undefined ? `<span class="chance-label">${percent(chance)}</span>` : ''}
    <img src="${item.image}" alt="${esc(item.name)}" loading="${eager ? 'eager' : 'lazy'}" draggable="false"><span class="item-name">${esc(item.name)}</span><span class="item-value"><span class="coin">✦</span>${money(item.value)}</span>${sale ? '<span class="sell-hint">Нажми, чтобы продать</span>' : ''}
  </${tag}>`;
}
const previewFeed = ['67', 'venuspino', 'dragon', 'burguro', 'garama', 'ketupatbro', 'cerberus'].map(itemId => ({ itemId, preview: true }));
function feedMarkup() {
  return `<section class="live-section" aria-label="Последние дропы"><div class="live-heading"><span class="live-dot"></span>Последние дропы</div><div class="live-track">${[...state.feed, ...(server ? [] : previewFeed)].slice(0, 12).map(drop => {
    const item = ITEM_BY_ID[drop.itemId];
    return `<div class="drop-pill ${item.rarity}"><img src="${item.image}" alt="${esc(item.name)}"><div><strong>${esc(item.name)}</strong>${!drop.preview ? `<small>${esc(drop.playerName || playerName)}</small>` : ''}<div class="drop-price">✦ ${money(item.value)}</div></div></div>`;
  }).join('')}</div></section>`;
}
function renderCases() {
  return `${feedMarkup()}<section><div class="page-head compact-head"><h1>Кейсы</h1><span class="section-count">${CASES.length}</span></div><div class="case-grid">${CASES.map(c => `<a href="#case/${c.id}" class="case-card ${c.id}" style="--hue:${c.hue}deg"><h3>${c.name}</h3><img class="case-art" src="${c.image}" alt="Кейс ${c.name}"><span class="case-price">${c.free ? c.free==='daily' ? 'Раз в 24 часа' : 'За подписку' : `<span class="coin">✦</span>${money(c.price)} <small>BStars</small>`}</span><span class="case-arrow">↗</span></a>`).join('')}</div></section>`;
}
function shuffledBrainrots() {
  const items = [...ITEMS];
  for (let i = items.length - 1; i > 0; i--) {
    const j = Math.floor(randomUnit() * (i + 1));
    [items[i], items[j]] = [items[j], items[i]];
  }
  return items;
}
function renderCase(caseConfig) {
  const preview = shuffledBrainrots();
  const claim=state.freeClaims?.[caseConfig.id], unavailable=server && caseConfig.free && claim && (caseConfig.free==='subscribe' || server.now()<claim+86400000);
  return `<a class="back" href="#cases">${icon('arrow')}Все кейсы</a><section><div class="case-page-heading"><h1>${caseConfig.name}</h1></div>
    <div class="roulette" aria-label="Рулетка открытия кейса"><div class="roulette-track">${preview.map(i => itemCard(i, { eager:true })).join('')}</div><div class="roulette-selection"></div></div>
    <div class="open-controls"><button class="primary" data-action="open-case" data-id="${caseConfig.id}" ${state.balance < caseConfig.price || unavailable ? 'disabled' : ''}>${icon('box')}${caseConfig.free ? unavailable ? caseConfig.free==='subscribe' ? 'Уже получен' : 'Доступен раз в 24 часа' : 'Открыть бесплатно' : `Открыть за <span class="coin">✦</span>${money(caseConfig.price)}`}</button>${fastButton()}</div>
    ${state.balance < caseConfig.price ? '<div class="demo-banner" style="margin:-16px 0 24px;text-align:center">Не хватает BStars. <button data-action="topup" style="color:var(--pink)">Пополнить баланс →</button></div>' : ''}
    <div class="contents-heading"><h2>Что внутри кейса</h2><button class="info-link" data-action="case-odds" data-id="${caseConfig.id}">Базовые шансы ⓘ</button></div><div class="item-grid">${caseConfig.drops.map(d => itemCard(ITEM_BY_ID[d.itemId], { chance: d.baseChance })).join('')}</div>
    </section>`;
}
function inventoryEmpty(upgrade = false) {
  return `<div class="empty-state ${upgrade ? '' : 'inventory-empty'}">${icon('box')}<strong>Инвентарь пуст</strong><p>Открой кейс, чтобы получить предмет.</p><a class="primary small-button" href="#cases">К кейсам ${icon('box')}</a></div>`;
}
function getSource() {
  sourceUids = new Set([...sourceUids].filter(uid => state.inventory.some(entry => entry.uid === uid)));
  const stake = buildUpgradeStake(state.inventory, sourceUids);
  if (!stake.entries.length) return null;
  const items = stake.entries.map(entry => ITEM_BY_ID[entry.itemId]);
  return { ...items[0], ...stake, items };
}
function getTarget() { return ITEM_BY_ID[targetId] || null; }
function gauge(chance) {
  const level = liquidLevel(chance);
  return `<div class="upgrade-circle ${chance ? 'ready' : ''}" role="img" aria-label="Шанс успеха ${percent(chance)}">
    <svg class="upgrade-gauge" viewBox="0 0 240 240" aria-hidden="true"><defs>
      <clipPath id="circle-clip"><circle cx="120" cy="120" r="104"/></clipPath>
      <clipPath id="water-clip"><rect id="water-mask" x="0" y="${level}" width="240" height="240"/></clipPath>
      <linearGradient id="liquid" gradientUnits="userSpaceOnUse" x1="0" y1="16" x2="0" y2="224"><stop stop-color="#fa70b8"/><stop offset=".55" stop-color="#a75dde"/><stop offset="1" stop-color="#64d9de"/></linearGradient>
      <radialGradient id="glass"><stop stop-color="#252033"/><stop offset="1" stop-color="#11101c"/></radialGradient>
      <pattern id="gauge-grid" width="18" height="18" patternUnits="userSpaceOnUse"><path d="M18 0H0V18" fill="none" stroke="#ffffff" stroke-opacity=".035" stroke-width=".6"/></pattern>
    </defs><circle cx="120" cy="120" r="116" fill="none" stroke="#ffffff0b" stroke-width=".7"/>
    <circle cx="120" cy="120" r="111" fill="none" stroke="#a699be" stroke-opacity=".28" stroke-width="2" stroke-dasharray="1 8"/>
    <circle cx="120" cy="120" r="104" fill="url(#glass)"/>
    <g clip-path="url(#circle-clip)"><rect x="0" y="0" width="240" height="240" fill="url(#gauge-grid)"/>
      <rect id="liquid-body" x="0" y="${level}" width="240" height="240" fill="url(#liquid)"/>
      <g clip-path="url(#water-clip)" class="liquid-bubbles"><circle class="bubble bubble-a" cx="65" cy="235" r="2.2"/><circle class="bubble bubble-b" cx="155" cy="238" r="3"/><circle class="bubble bubble-c" cx="190" cy="241" r="1.5"/><circle class="bubble bubble-d" cx="100" cy="235" r="1.7"/></g>
      <g id="liquid-surface" transform="translate(0 ${level})"><path class="liquid-wave" d="M-240 0Q-210 -3-180 0T-120 0T-60 0T0 0T60 0T120 0T180 0T240 0T300 0T360 0T420 0T480 0" fill="none" stroke="#ffb7dc" stroke-width="1.2"/><path d="M0 0H240" stroke="#ffffff" stroke-opacity=".12" stroke-width=".5"/></g>
    </g><circle cx="120" cy="120" r="104" fill="none" stroke="#ffffff13" stroke-width="1"/>
    <path class="glass-highlight" d="M39 77a92 92 0 0 1 119-41" fill="none" stroke="#ffffff" stroke-opacity=".1" stroke-width="1.5"/>
    <line id="landing-trail" x1="120" y1="120" x2="120" y2="120" stroke="#fff" stroke-width=".8" stroke-dasharray="2 3" opacity="0"/>
    <circle id="landing-ripple" cx="120" cy="120" r="3" fill="none" stroke="#fff" stroke-width="1.5" opacity="0"/>
    <circle id="landing-dot" cx="120" cy="120" r="3.3" fill="#fff" opacity="0"/>
    </svg><div class="gauge-copy"><strong>${percent(chance)}</strong><small>шанс успеха</small></div><div class="pointer-orbit"><svg class="pointer-tip" viewBox="0 0 16 20" aria-hidden="true"><path d="M1 1h14L8 18Z" fill="#ff9bce" stroke="#ffb5dc" stroke-width="1"/></svg></div></div>`;
}
function animateGauge(chance) {
  cancelAnimationFrame(gaugeFrame);
  const from = displayedChance, start = performance.now();
  const body = $('#liquid-body'), mask = $('#water-mask'), surface = $('#liquid-surface'), number = $('.gauge-copy strong');
  if (!body) return;
  function update(now) {
    const t = reducedMotion.matches ? 1 : Math.max(0, Math.min((now - start) / 850, 1));
    displayedChance = t === 1 ? chance : Math.max(0, Math.min(1, from + (chance - from) * (1 - (1 - t) ** 3)));
    const y = liquidLevel(displayedChance);
    body.setAttribute('y', y); mask.setAttribute('y', y); surface.setAttribute('transform', `translate(0 ${y})`); number.textContent = percent(displayedChance);
    if (t < 1) gaugeFrame = requestAnimationFrame(update);
  }
  gaugeFrame = requestAnimationFrame(update);
}
function slotMarkup(item, label) { return `<div class="upgrade-slot"><span class="slot-label">${label}</span>${item ? `<img src="${item.image}" alt="${esc(item.name)}"><strong>${esc(item.name)}</strong><span class="slot-price">✦ ${money(item.value)}</span>` : '<div class="slot-empty">+</div><strong>Выбери предмет</strong>'}</div>`; }
function sourceSlotMarkup(source) {
  if (!source || source.entries.length === 1) return slotMarkup(source, 'ИСХОДНЫЕ ПРЕДМЕТЫ');
  return `<div class="upgrade-slot stake-slot"><span class="slot-label">ИСХОДНЫЕ ПРЕДМЕТЫ</span><div class="stake-stack">${source.items.slice(0,3).map((item,index)=>`<img src="${item.image}" alt="${esc(item.name)}" style="--stack-index:${index}">`).join('')}${source.items.length > 3 ? `<span class="stack-more">+${source.items.length-3}</span>` : ''}</div><strong>Предметов: ${source.entries.length}</strong><span class="slot-price">✦ ${money(source.value)}</span></div>`;
}
function targetsMarkup() {
  const source = getSource();
  const targets = ITEMS.filter(i => (!source || i.value > source.value) && i.name.toLowerCase().includes(targetSearch.toLowerCase()));
  return targets.length ? targets.map(i => itemCard(i, { action: 'select-target', selected: i.id === targetId })).join('') : '<div class="empty-state" style="grid-column:1/-1"><p>Подходящих предметов нет. Измени поиск или исходный предмет.</p></div>';
}
function renderUpgrade() {
  const source = getSource();
  if (source && getTarget()?.value <= source.value) targetId = null;
  const target = getTarget(); const chance = upgradeChance(source, target);
  return `<div class="page-head upgrade-head compact-head"><h1>Апгрейдер</h1></div>
    <section aria-label="Апгрейдер"><div class="upgrade-machine"><div class="upgrade-stage">${sourceSlotMarkup(source)}${gauge(chance)}${slotMarkup(target, 'ЦЕЛЕВОЙ ПРЕДМЕТ')}</div><div class="upgrade-controls"><div class="quick-buttons" aria-label="Подбор цели по шансу">${[75,50,20].map(p => `<button data-action="quick" data-id="${p}" class="${quick === p ? 'active' : ''}">${p}%</button>`).join('')}</div><div class="game-actions"><button class="primary" data-action="upgrade" ${!chance ? 'disabled' : ''}>${icon('upgrade')}Апгрейдить</button>${fastButton()}</div><p class="upgrade-hint">${source && target ? 'Попадание в заполненную область — успех. При неудаче выбранные предметы теряются.' : source && source.value >= ITEMS.at(-1).value ? 'Нет цели дороже суммы выбранных предметов' : 'Выбери один или несколько предметов и цель'}</p></div></div>
    <div class="selection-columns"><section class="selection-panel"><div class="selection-title"><h2>Твой инвентарь</h2><span>${state.inventory.length} шт.</span></div>${state.inventory.length ? `<div class="stake-summary"><span>Выбрано: ${sourceUids.size}<strong>✦ ${money(source?.value || 0)}</strong></span><button data-action="clear-source" ${sourceUids.size ? '' : 'disabled'}>Сбросить</button></div><div class="item-grid">${state.inventory.map(i => itemCard(ITEM_BY_ID[i.itemId], { action: 'select-source', id: i.uid, selected: sourceUids.has(i.uid) })).join('')}</div>` : inventoryEmpty(true)}</section>
    <section class="selection-panel"><div class="selection-title"><h2>Хочу получить</h2><span>BStars</span></div><label class="search">${icon('search')}<input id="target-search" type="search" value="${esc(targetSearch)}" placeholder="Найти брейнрота" aria-label="Найти желаемого брейнрота"></label><div class="item-grid" id="target-grid">${targetsMarkup()}</div></section></div></section>`;
}
function renderProfile() {
  const totalValue = state.inventory.reduce((sum, i) => sum + ITEM_BY_ID[i.itemId].value, 0);
  const photo = telegramUser?.photo_url;
  const safePhoto = photo && /^https:\/\//i.test(photo) ? photo : null;
  return `<div class="profile-head compact-head"><h1>Профиль</h1><a class="admin-link" href="#admin">${icon('shield')}Админ-панель</a></div><section class="profile-card"><div class="avatar">${safePhoto ? `<img src="${esc(safePhoto)}" alt="Аватар пользователя" referrerpolicy="no-referrer">` : esc(playerName.replace('@','').slice(0,2).toUpperCase())}</div><div class="profile-identity"><h2>${esc(playerName)}</h2></div><div class="profile-stats"><div><strong>${money(state.stats.opened)}</strong><small>Кейсов открыто</small></div><div><strong>${money(state.stats.upgrades)}</strong><small>Апгрейдов</small></div><div><strong>${money(state.stats.wins)}</strong><small>Успешных</small></div></div></section>
    <section class="promo-panel">${icon('gift')}<div class="promo-copy"><strong>Промокод</strong></div><form class="promo-form" id="promo-form"><input name="promo" autocomplete="off" aria-label="Промокод" placeholder="Промокод" maxlength="30" required><button class="primary">Активировать</button></form></section>
    <section><div class="inventory-heading"><h2>Инвентарь <span>${state.inventory.length}</span></h2><div class="wallet-actions"><button class="primary" data-action="topup">${icon('plus')}Пополнить</button><button class="secondary" data-action="withdraw">${icon('withdraw')}Вывод</button></div></div><div class="inventory-meta"><span>Нажми на брейнрота, чтобы продать</span><span>Стоимость: ✦ ${money(totalValue)}</span></div>${state.inventory.length ? `<div class="item-grid inventory-grid">${state.inventory.map(i => itemCard(ITEM_BY_ID[i.itemId], { action: 'sell', id: i.uid, sale: true })).join('')}</div>` : inventoryEmpty()}
    ${!storageWorks ? '<p class="storage-error">Браузер запретил локальное сохранение. После перезагрузки прогресс может сброситься.</p>' : ''}</section>${renderHistory(state,historyFilter,historyLimit,featureUI)}`;
}
function slotSymbol(itemId) {
  const item = ITEM_BY_ID[itemId];
  return `<div class="reel-symbol ${item.rarity}"><img src="${item.image}" alt="${esc(item.name)}" draggable="false"><span>${esc(item.name)}</span></div>`;
}
function renderSlots() {
  const bet = state.inventory.find(entry => entry.uid === slotUid);
  if (!bet) slotUid = null;
  const item = bet && ITEM_BY_ID[bet.itemId];
  const last = state.slotResult;
  const symbols = last?.symbols || ['67','bananito','foxini'];
  return `<div class="compact-head"><h1>Слоты</h1></div><section class="slots-layout"><div class="slots-cabinet ${last?.multiplier ? 'has-win' : ''}">
    <div class="slots-topline">${icon('slots')}<span>3 БАРАБАНА</span><span class="slots-indicator"></span></div>
    <div class="slots-reels" aria-label="Три барабана слотов">${symbols.map((id,index)=>`<div class="slot-window"><div class="slot-track" data-reel="${index}">${slotSymbol(id)}</div></div>`).join('')}<div class="slots-payline" aria-hidden="true"></div></div>
    <div class="slots-readout" role="status" aria-live="polite">${last ? `${last.multiplier ? `Выигрыш ×${last.multiplier} · ✦ ${money(last.payout)}` : 'Без совпадений'}<small>${last.symbols.map(id=>esc(ITEM_BY_ID[id].name)).join(' · ')}</small>` : 'Выбери предмет для ставки<small>Совпадения учитываются на центральной линии</small>'}</div>
    <div class="slot-stake"><span>СТАВКА</span>${item ? `<img src="${item.image}" alt=""><div><strong>${esc(item.name)}</strong><small>✦ ${money(item.value)} BStars</small></div><button data-action="clear-slot" aria-label="Убрать ставку">×</button>` : '<strong>Предмет из инвентаря</strong>'}</div>
    <div class="game-actions"><button class="primary" data-action="spin-slots" ${!item ? 'disabled' : ''}>${icon('slots')}Крутить</button>${fastButton()}</div>
    <div class="slot-payouts"><div><span>2 одинаковых</span><strong>×2</strong></div><div><span>3 одинаковых</span><strong>×5</strong></div></div>
    <p class="slot-rule">Ставка расходуется за одну попытку. Выигрыш поступает на баланс в BStars.</p>
    </div><section class="selection-panel slot-inventory"><div class="selection-title"><h2>Твой инвентарь</h2><span>${state.inventory.length} шт.</span></div>${state.inventory.length ? `<p class="slot-selection-note">Выбери один предмет для ставки</p><div class="item-grid">${state.inventory.map(entry=>itemCard(ITEM_BY_ID[entry.itemId],{action:'select-slot',id:entry.uid,selected:entry.uid===slotUid})).join('')}</div>` : inventoryEmpty(true)}</section></section>`;
}
function parseRoute() {
  const hash = location.hash.slice(1);
  return ['rocket','mines','admin','slots','upgrade','profile','cases'].includes(hash) || (hash.startsWith('case/') && CASE_BY_ID[hash.slice(5)]) ? hash : 'cases';
}
function render({ scroll = false } = {}) {
  if (server?.locked) { $('#main').innerHTML=`<section class="empty-state"><h1>Brainrot Freebie</h1><p>${esc(server.message)}</p></section>`; $('#balance').textContent='0'; $('.bottom-nav').hidden=true; $('.balance').disabled=true; return; }
  cancelAnimationFrame(gaugeFrame);
  const route = parseRoute(); activeRoute = route;
  const tab = route.startsWith('case/') ? 'cases' : route==='admin' ? 'profile' : route;
  mineUids = new Set([...mineUids].filter(uid=>state.inventory.some(entry=>entry.uid===uid)));
  rocketUids=new Set([...rocketUids].filter(uid=>state.inventory.some(entry=>entry.uid===uid)));
  if (state.mines?.status==='active') mineCount=state.mines.bombCount;
  const rocketState=server ? {...state,rocket:sharedRocket(state)} : state;
  $('#main').innerHTML = route.startsWith('case/') ? renderCase(CASE_BY_ID[route.slice(5)]) : route === 'upgrade' ? renderUpgrade() : route === 'slots' ? renderSlots() : route==='rocket' ? renderRocket(rocketState,rocketUids,rocketAuto,rocketAutoTarget,{...featureUI,server:!!server,now:server?.now}) : route==='mines' ? renderMines(state,mineUids,mineCount,featureUI) : route==='admin' ? server && !state.isAdmin ? '<div class="empty-state">Доступ запрещён</div>' : renderAdmin(state,playerName,{...featureUI,server:!!server}) : route === 'profile' ? renderProfile() : renderCases();
  if (server && route==='profile') enhanceServerProfile();
  if(server) {
    if(state.gamesPaused) $('#main').insertAdjacentHTML('afterbegin','<p class="service-notice">Приём новых ставок приостановлен. Активные игры можно завершить.</p>');
    if(['upgrade','slots','mines','rocket'].includes(route)) {
      const maxStake=route==='rocket' ? Math.min(state.limits.max_stake,state.limits.max_payout/100) : route==='slots' ? Math.min(state.limits.max_stake,state.limits.max_payout/5) : state.limits.max_stake;
      $('.compact-head')?.insertAdjacentHTML('afterend',`<p class="game-limits">Макс. ставка: ${money(maxStake)} BStars · Макс. выплата: ${money(state.limits.max_payout)} BStars${route==='rocket' ? `<br>Общий лимит ставок раунда: ${money(state.round?.maxTotalStake || state.limits.rocket_round_stake)} BStars` : ''}</p>`);
    }
    if(state.gamesPaused) document.querySelectorAll('[data-action="open-case"],[data-action="upgrade"],[data-action="spin-slots"],[data-action="mine-start"],[data-action="rocket-start"]').forEach(b=>b.disabled=true);
    if(route==='admin' && state.isAdmin) enhanceFinancialAdmin();
  }
  document.querySelectorAll('[data-tab]').forEach(el => { el.classList.toggle('active', el.dataset.tab === tab); if (el.dataset.tab === tab) el.setAttribute('aria-current','page'); else el.removeAttribute('aria-current'); });
  $('#balance').textContent = money(state.balance);
  if (isTelegram) { try { route === 'cases' ? tg.BackButton.hide() : tg.BackButton.show(); } catch {} }
  if (scroll) { window.scrollTo({ top: 0, behavior: 'instant' }); $('#main').focus({ preventScroll: true }); }
  if (route.startsWith('case/')) centerPreview();
  if (route === 'upgrade') animateGauge(upgradeChance(getSource(), getTarget()));
  else displayedChance = 0;
  if (scroll && !reducedMotion.matches) $('#main').animate([{opacity:0,transform:'translateY(8px)'},{opacity:1,transform:'translateY(0)'}],{duration:320,easing:'ease-out'});
  runRocket();
}
function centerPreview() {
  const track = $('.roulette-track'); if (!track) return;
  const cards = track.children; const card = cards[3];
  track.style.transform = `translateX(${$('.roulette').clientWidth/2 - card.offsetLeft - card.offsetWidth/2}px)`;
}
window.addEventListener('hashchange', () => { if (busy) { history.replaceState(null,'',`#${activeRoute}`); return; } closeModal(); render({ scroll:true }); });
window.addEventListener('resize', () => { if (!busy && $('.roulette-track')) centerPreview(); });
window.addEventListener('storage', event => { if (event.key === SETTINGS.storageKey && !busy) { try { state = validateState(JSON.parse(event.newValue)); closeModal(); render(); } catch {} } });

function addInventory(itemId) {
  const uid = crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.floor(randomUnit()*1e12)}`;
  state.inventory.unshift({ uid, itemId }); return uid;
}
function pushFeed(itemId) { state.feed.unshift({ itemId }); state.feed = state.feed.slice(0, 12); }
function watchTicks(animation, count) {
  let frameId = 0, previous = 0, stopped = false;
  function frame() {
    if (stopped) return;
    const progress = animation.effect?.getComputedTiming().progress;
    const step = Math.floor((progress || 0)*count);
    if (step > previous) { sound.play('tick'); previous = step; }
    if (animation.playState === 'running') frameId = requestAnimationFrame(frame);
  }
  frameId = requestAnimationFrame(frame);
  return () => { stopped = true; cancelAnimationFrame(frameId); };
}
async function openCase(caseId) {
  if (busy) return;
  const c = CASE_BY_ID[caseId]; if (!c || state.balance < c.price) return toast('Не хватает BStars. Пополни баланс бесплатно в профиле.');
  const fast = fastMode || reducedMotion.matches;
  const response=server ? await serverAction('case',{caseId}) : null;
  if (server && !response) return;
  const itemId = server ? response.result.itemId : rollCase(c), item = ITEM_BY_ID[itemId];
  // Commit the complete outcome before animation: closing/reloading cannot lose
  // a charged item or replay a pending transaction.
  let uid=response?.result.uid;
  if (!server) { state.balance -= c.price; uid = addInventory(itemId); state.stats.opened++; pushFeed(itemId);
  state = recordOperation(state,{type:'case',title:`Кейс · ${c.name}`,detail:`Получен ${item.name} · стоимость ${item.value} BStars`,delta:-c.price}); } persist();
  setBusy(true); haptic('medium');
  const button = $('[data-action="open-case"]'); button.disabled = true; button.textContent = 'Открываем…';
  const track = $('.roulette-track');
  // Decorative cards use the entire catalog; only the winning card uses case odds.
  const sequence = [...shuffledBrainrots(), ...shuffledBrainrots()]; sequence[28] = item;
  track.innerHTML = sequence.map(i => itemCard(i, { eager:true })).join('');
  const first = track.children[3], winner = track.children[28];
  const start = $('.roulette').clientWidth/2 - first.offsetLeft - first.offsetWidth/2;
  const end = $('.roulette').clientWidth/2 - winner.offsetLeft - winner.offsetWidth/2;
  let stopTicks = () => {};
  try {
    const animation = track.animate([{ transform: `translateX(${start}px)` }, { transform: `translateX(${end}px)` }], { duration: fast ? 350 : 4700, easing:'cubic-bezier(.12,.7,.12,1)', fill:'forwards' });
    stopTicks = watchTicks(animation,25); await animation.finished;
    track.style.transform = `translateX(${end}px)`; animation.cancel();
  } catch { track.style.transform = `translateX(${end}px)`; } finally { stopTicks(); }
  sound.play('win');
  setBusy(false); notifyHaptic(true); button.disabled = state.balance < c.price || !!(server && c.free); button.innerHTML = c.free ? c.free==='daily' ? 'Доступен раз в 24 часа' : 'Уже получен' : `${icon('box')}Открыть за <span class="coin">✦</span>${money(c.price)}`;
  openModal(`<div class="modal-content ${item.rarity}"><h2>Получен предмет</h2><div class="result-art"><img src="${item.image}" alt="${esc(item.name)}"></div><div class="result-name">${esc(item.name)}</div><div class="result-value">✦ ${money(item.value)} <small style="font-size:11px">BStars</small></div><div class="result-rarity">${RARITIES[item.rarity]}</div><div class="modal-actions"><button class="primary" data-action="keep-drop">Оставить</button><button class="secondary" data-action="confirm-sell" data-id="${uid}">Продать · ${money(item.value)}</button></div><button class="info-link" style="margin:19px auto 0" data-action="to-upgrade" data-id="${uid}">В апгрейдер ↗</button></div>`);
}
function sellDialog(uid) {
  const owned = state.inventory.find(i => i.uid === uid); if (!owned) return;
  const item = ITEM_BY_ID[owned.itemId];
  openModal(`<div class="modal-content ${item.rarity}"><h2>Продать предмет?</h2><div class="result-art"><img src="${item.image}" alt="${esc(item.name)}"></div><div class="result-name">${esc(item.name)}</div><p>На баланс поступит <strong style="color:#ffcf76">${money(item.value)} BStars</strong>.</p><div class="modal-actions"><button class="secondary" data-action="close-modal">Оставить</button><button class="primary" data-action="confirm-sell" data-id="${uid}">Продать</button></div></div>`);
}
async function sell(uid) {
  if (server) { const response=await serverAction('sale',{uid}); if (response) {closeModal(); render(); toast('Предмет продан');} return; }
  const index = state.inventory.findIndex(i => i.uid === uid); if (index < 0) return;
  const item = ITEM_BY_ID[state.inventory[index].itemId];
  state.inventory.splice(index, 1); state.balance += item.value;
  sourceUids.delete(uid);
  state = recordOperation(state,{type:'sale',title:'Продажа предмета',detail:item.name,delta:item.value});
  persist(); closeModal(); render(); haptic(); toast(`Продано! +${money(item.value)} BStars`);
}
function quickTarget(p) {
  const source = getSource(); if (!source) return toast('Сначала выбери брейнрота из инвентаря.');
  const valid = ITEMS.filter(i => i.value > source.value);
  if (!valid.length) return toast('Для этого предмета пока нет более дорогой цели.');
  const desired = Number(p)/100;
  targetId = valid.reduce((a,b) => Math.abs(upgradeChance(source,a)-desired) <= Math.abs(upgradeChance(source,b)-desired) ? a : b).id;
  quick = Number(p); targetSearch = ''; render(); haptic();
}
async function upgrade() {
  if (busy) return;
  const fast = fastMode || reducedMotion.matches;
  const source = getSource(), target = getTarget(), chance = upgradeChance(source,target);
  if (!chance) return toast('Выбери исходный и желаемый предмет.');
  const stake = buildUpgradeStake(state.inventory, sourceUids); if (!stake.entries.length) return;
  const response=server ? await serverAction('upgrade',{uids:[...sourceUids],targetId:target.id}) : null;
  if (server && !response) return;
  const landing = server ? response.result.landing : upgradeLanding(chance); const win = landing.win;
  if (!server) state.inventory = stake.remaining;
  const wonUid = server ? response.result.wonUid : win ? addInventory(target.id) : null;
  if (!server) {
  state.stats.upgrades++; if (win) { state.stats.wins++; pushFeed(target.id); }
  state = recordOperation(state,{type:'upgrade',title:'Апгрейд',status:win ? 'win' : 'lose',detail:`Ставка: ${stake.entries.length} предметов · ${stake.value} BStars; цель: ${target.name} · ${target.value} BStars; шанс: ${percent(chance)}. ${win ? 'Предмет получен.' : 'Предметы потрачены.'}`});
  }
  persist(); setBusy(true); haptic('medium');
  displayedChance = chance; animateGauge(chance);
  $('.upgrade-circle').classList.add('spinning'); $('.upgrade-machine').classList.add('running');
  $('[data-action="upgrade"]').disabled = true; $('[data-action="upgrade"]').textContent = 'Апгрейдим…';
  document.querySelectorAll('.quick-buttons button,.selection-panel button,.selection-panel input').forEach(el => el.disabled = true);
  const pointer = $('.pointer-orbit'); const turns = 360 * 6 + landing.angle;
  let stopTicks = () => {};
  try { const animation = pointer.animate([{transform:'rotate(0deg)'},{transform:`rotate(${turns}deg)`}],{duration:fast ? 260 : 3900,easing:'cubic-bezier(.14,.65,.12,1)',fill:'forwards'}); stopTicks = watchTicks(animation,turns/12); await animation.finished; pointer.style.transform=`rotate(${turns}deg)`; animation.cancel(); } catch { pointer.style.transform=`rotate(${turns}deg)`; } finally { stopTicks(); }
  $('.upgrade-circle').classList.remove('spinning'); $('.upgrade-circle').classList.add('landing');
  const angle = landing.angle * Math.PI / 180;
  const startX = 120 + Math.sin(angle) * 104, startY = 120 - Math.cos(angle) * 104;
  const dot = $('#landing-dot'), trail = $('#landing-trail'), ripple = $('#landing-ripple');
  dot.setAttribute('opacity', '1'); trail.setAttribute('opacity', '.5');
  trail.setAttribute('x1', startX); trail.setAttribute('y1', startY);
  await new Promise(resolve => {
    const start = performance.now();
    function frame(now) {
      const t = reducedMotion.matches ? 1 : Math.max(0, Math.min((now-start)/(fast ? 100 : 650),1)), eased = 1-(1-t)**3;
      const x = startX + (landing.x-startX)*eased, y = startY + (landing.y-startY)*eased;
      dot.setAttribute('cx',x); dot.setAttribute('cy',y); trail.setAttribute('x2',x); trail.setAttribute('y2',y);
      if (t < 1) requestAnimationFrame(frame); else resolve();
    }
    requestAnimationFrame(frame);
  });
  ripple.setAttribute('cx',landing.x); ripple.setAttribute('cy',landing.y); ripple.setAttribute('opacity','1');
  $('.upgrade-circle').classList.add(win ? 'won' : 'lost'); notifyHaptic(win);
  sound.play(win ? 'win' : 'lose');
  if (!reducedMotion.matches) {
    const rippleAnimation = ripple.animate([{transform:'scale(1)',opacity:1},{transform:'scale(7)',opacity:0}],{duration:fast ? 160 : 850,easing:'ease-out'});
    try { await rippleAnimation.finished; } catch {}
  }
  setBusy(false); sourceUids.clear(); targetId = null; quick = null; render();
  openModal(`<div class="modal-content ${win ? target.rarity : source.rarity}"><h2>${win ? 'Апгрейд выполнен' : 'Апгрейд не удался'}</h2>${win ? `<div class="result-art"><img src="${target.image}" alt="${esc(target.name)}"></div><div class="result-name">${esc(target.name)}</div><div class="result-value">✦ ${money(target.value)}</div>` : '<div class="modal-status-icon" style="color:#e38fa9">↺</div>'}<p style="margin-top:14px">${win ? 'Предмет добавлен в инвентарь.' : `Потрачено предметов: ${stake.entries.length} · ✦ ${money(stake.value)}`}<br>Шанс: ${percent(chance)}.</p><div class="modal-actions"><button class="primary" data-action="close-modal">Понятно</button>${win ? `<button class="secondary" data-action="to-upgrade" data-id="${wonUid}">Ещё апгрейд</button>` : '<button class="secondary" data-action="goto-cases">К кейсам</button>'}</div></div>`);
}
async function spinSlots() {
  if (busy) return;
  if (!state.inventory.some(entry=>entry.uid===slotUid)) return toast('Выбери предмет для ставки.');
  const fast = fastMode || reducedMotion.matches;
  if (server) { if (!await serverAction('slots',{uid:slotUid})) return; }
  else state = settleSlots(state,slotUid);
  const result = state.slotResult;
  if (!server) state = recordOperation(state,{type:'slots',title:'Слоты',status:result.multiplier ? 'win' : 'lose',delta:result.payout,detail:`Ставка: ${result.betValue} BStars · ${result.symbols.map(id=>ITEM_BY_ID[id].name).join(' / ')} · ×${result.multiplier}`});
  persist({balanceVisible:false}); setBusy(true); haptic('medium');
  $('.slots-cabinet').classList.remove('has-win'); $('.slots-cabinet').classList.add('running');
  $('.slots-readout').textContent = 'Барабаны вращаются…';
  $('[data-action="spin-slots"]').disabled = true;
  $('[data-action="spin-slots"]').textContent = 'Крутим…';
  document.querySelectorAll('.slot-inventory button,.slot-stake button').forEach(button=>button.disabled=true);
  const tracks = [...document.querySelectorAll('[data-reel]')];
  await Promise.all(tracks.map(async (track,index)=>{
    track.setAttribute('aria-hidden','true');
    const initial = track.innerHTML;
    const filler = Array.from({length:27},()=>ITEMS[Math.floor(randomUnit()*ITEMS.length)].id);
    track.innerHTML = initial + filler.map(slotSymbol).join('') + slotSymbol(result.symbols[index]);
    const distance = track.lastElementChild.offsetTop-track.firstElementChild.offsetTop;
    const duration = reducedMotion.matches ? 100 : fast ? 400+index*120 : 2000+index*500;
    let stopTicks = ()=>{};
    try {
      const animation = track.animate([{transform:'translateY(0)'},{transform:`translateY(-${distance}px)`}],{duration,easing:'cubic-bezier(.1,.75,.1,1)',fill:'forwards'});
      stopTicks = watchTicks(animation,28); await animation.finished;
      track.style.transform = `translateY(-${distance}px)`; animation.cancel();
    } catch { track.style.transform = `translateY(-${distance}px)`; } finally { stopTicks(); }
    sound.play('tick');
  }));
  slotUid = null; setBusy(false); render();
  if (result.multiplier) {
    const matched = result.symbols.filter((id,_,ids)=>ids.filter(other=>other===id).length>1);
    document.querySelectorAll('.slot-window').forEach((window,index)=>window.classList.toggle('match',matched.includes(result.symbols[index])));
  }
  sound.play(result.multiplier ? 'win' : 'lose'); notifyHaptic(Boolean(result.multiplier));
  toast(result.multiplier ? `${result.multiplier===5 ? 'Три совпадения' : 'Два совпадения'}! +${money(result.payout)} BStars` : 'Без совпадений');
}
function fairness(caseId) {
  const c = CASE_BY_ID[caseId];
  if (!c) return;
  const rows = distribution(c).map(d => `<tr><td>${esc(ITEM_BY_ID[d.itemId].name)}</td><td>${percent(d.baseChance)}</td><td>${percent(d.chance)}</td></tr>`).join('');
  openModal(`<div class="modal-content"><h2>${c.name} · шансы</h2><div class="fairness-text"><table class="fairness-table"><thead><tr><th>Предмет</th><th>Базовый шанс</th><th>Шанс выпадения</th></tr></thead><tbody>${rows}</tbody></table></div><div class="modal-actions"><button class="primary" data-action="close-modal">Понятно</button></div></div>`);
}
function topup() { if (server) return depositDialog(); state.balance += SETTINGS.topUp; state = recordOperation(state,{type:'topup',title:'Пополнение',detail:'Начисление BStars',delta:SETTINGS.topUp}); persist(); closeModal(); render(); haptic(); toast(`Пополнение +${SETTINGS.topUp} BStars`); }

async function mineAction(action,id) {
  if (server) { const response=await serverAction(action==='mine-start' ? 'mines-start' : action==='mine-cash' ? 'mines-cash' : 'mines-reveal',action==='mine-start' ? {uids:[...mineUids],bombCount:mineCount} : action==='mine-cell' ? {index:Number(id)} : {}); if(response) {mineUids.clear(); render(); sound.play(state.mines.status==='lost' ? 'lose' : state.mines.status==='won' ? 'win' : 'tick');} return; }
  try {
    if (action==='mine-start') { state=startMines(state,mineUids,mineCount); mineUids.clear(); sound.play('tick'); }
    else if (action==='mine-cash') { state=cashMines(state); sound.play('win'); notifyHaptic(true); }
    else { state=revealMine(state,Number(id)); sound.play(state.mines.status==='lost' ? 'lose' : state.mines.status==='won' ? 'win' : 'tick'); haptic(); if (state.mines.status!=='active') notifyHaptic(state.mines.status==='won'); }
    persist(); render();
    if (state.mines.status==='won') toast(`Забрано +${money(state.mines.payout)} BStars`);
  } catch(error) { toast(error.message); }
}
function saveRocketPrefs() { try { localStorage.setItem('brainrot-freebie-rocket',JSON.stringify({enabled:rocketAuto,target:rocketAutoTarget})); } catch {} }
function rocketResult() {
  const game=state.rocket;
  sound.play(game.status==='won' ? 'win' : 'lose'); notifyHaptic(game.status==='won');
  toast(game.status==='won' ? `${game.automatic ? 'Автозабор' : 'Забрано'} ×${game.cashAt.toFixed(2)} · +${money(game.payout)} BStars` : `Взрыв на ×${(Math.floor(game.crash*100)/100).toFixed(2)}`);
}
async function rocketAction(action) {
  if (server) { const response=await serverAction(action==='rocket-start' ? 'rocket-bet' : 'rocket-cash',action==='rocket-start' ? {roundId:state.round.id,uids:[...rocketUids],autoCash:rocketAuto ? Number($('#rocket-auto-value').value) : null} : {}); if(response) {rocketUids.clear(); render(); if(state.rocket.status!=='active') rocketResult();} return; }
  try {
    if (action==='rocket-start') { state=startRocket(state,rocketUids,rocketAuto ? Number($('#rocket-auto-value').value) : null); rocketUids.clear(); rocketCompletedId=null; sound.play('tick'); }
    else { state=cashRocket(state); rocketResult(); }
    persist(); render();
  } catch(error) { toast(error.message); }
}
function runRocket() {
  if (server) { runServerRocket(); return; }
  if (rocketFrame) return;
  if (!state.rocket || state.rocket.status!=='active'&&rocketFinished(state.rocket)) return;
  function frame() {
    rocketFrame=0;
    const now=Date.now(), before=state;
    state=advanceRocket(state,now);
    const game=state.rocket;
    if (!game) return;
    if (state!==before) {
      persist(); rocketResult();
      if (!busy && activeRoute==='rocket') render();
      else if (activeRoute==='profile' && $('#operation-history')) $('#operation-history').outerHTML=renderHistory(state,historyFilter,historyLimit,featureUI);
    }
    const ended=rocketFinished(game,now);
    if (activeRoute==='rocket' && !busy) {
      if (ended && rocketCompletedId!==game.id) { rocketCompletedId=game.id; render(); }
      const value=rocketValue(game,now), countdown=now<game.startAt, geo=rocketGeometry(value);
      if ($('#rocket-multiplier')) {
        $('#rocket-multiplier').textContent=countdown ? `${((game.startAt-now)/1000).toFixed(1)}с` : `${(Math.floor(value*100)/100).toFixed(2)}×`;
        $('#rocket-label').textContent=countdown ? 'До старта' : ended ? game.capped ? 'Достигнуто ×100' : 'Ракета взорвалась' : 'В полёте';
        $('#rocket-machine').classList.toggle('countdown',countdown); $('#rocket-machine').classList.toggle('flying',!countdown&&!ended);
        $('#rocket-path').setAttribute('d',geo.path); $('#rocket-area').setAttribute('d',`${geo.path} L${geo.x} 290H55Z`);
        $('#rocket-ship').setAttribute('transform',`translate(${geo.x} ${geo.y}) rotate(${geo.angle})`); $('#rocket-blast').setAttribute('transform',`translate(${geo.x} ${geo.y})`);
        const button=$('[data-action="rocket-cash"]');
        if (button) button.disabled=countdown||game.status!=='active'||ended;
        if ($('#rocket-cash-value')) $('#rocket-cash-value').textContent=money(Math.round(game.stakeValue*Math.floor(value*100))/100);
      }
    }
    if (!ended && !rocketFrame) rocketFrame=requestAnimationFrame(frame);
    else if (ended && rocketFrame) { cancelAnimationFrame(rocketFrame); rocketFrame=0; }
  }
  rocketFrame=requestAnimationFrame(frame);
}
document.addEventListener('visibilitychange',()=>{ if (!document.hidden) runRocket(); });
let serverRequestPending=false, serverRocketFrame=0;
function adoptServerState(next) {
  if (next.serverNow<(state.serverNow || 0)) return;
  const merged=new Map([...next.history,...state.history].map(e=>[e.id,e]));
  next.history=[...merged.values()].map(e=>next.history.find(n=>n.id===e.id) || e).sort((a,b)=>Date.parse(b.createdAt)-Date.parse(a.createdAt));
  state=next; server.state=next; server.offset=next.serverNow-Date.now(); persist();
}
async function serverAction(action,body) {
  if (!server || server.locked || serverRequestPending || busy) return null;
  serverRequestPending=true; setBusy(true);
  try { const response=await server.mutate(action,body); adoptServerState(response.state); return response; }
  catch(error) {toast(error.message); return null;}
  finally {serverRequestPending=false; setBusy(false);}
}
function canSelectRocket() { return server ? state.round && !state.round.ended && server.now()<state.round.startAt && state.rocket?.roundId!==state.round.id : !state.rocket || rocketFinished(state.rocket); }
function runServerRocket() {
  if (serverRocketFrame || activeRoute!=='rocket' || server.locked) return;
  function frame() {
    serverRocketFrame=0;
    if (activeRoute!=='rocket' || !$('#rocket-multiplier')) return;
    const game=sharedRocket(state); if(!game) return;
    const now=server.now(), countdown=now<game.startAt, value=rocketValue(game,now), geo=rocketGeometry(value);
    $('#rocket-multiplier').textContent=countdown ? `${Math.max(0,(game.startAt-now)/1000).toFixed(1)}с` : `${(Math.floor(value*100)/100).toFixed(2)}×`;
    $('#rocket-label').textContent=countdown ? 'Приём ставок' : game.ended ? game.capped ? 'Достигнуто ×100' : 'Ракета взорвалась' : 'В полёте';
    $('#rocket-machine').classList.toggle('countdown',countdown); $('#rocket-machine').classList.toggle('flying',!countdown&&!game.ended);
    $('#rocket-path').setAttribute('d',geo.path); $('#rocket-area').setAttribute('d',`${geo.path} L${geo.x} 290H55Z`);
    $('#rocket-ship').setAttribute('transform',`translate(${geo.x} ${geo.y}) rotate(${geo.angle})`); $('#rocket-blast').setAttribute('transform',`translate(${geo.x} ${geo.y})`);
    const cash=$('[data-action="rocket-cash"]'); if(cash) cash.disabled=busy||countdown||game.status!=='active'||game.ended;
    const stake=state.inventory.filter(e=>rocketUids.has(e.uid)).reduce((s,e)=>s+ITEM_BY_ID[e.itemId].value,0);
    const launch=$('[data-action="rocket-start"]'); if(launch) launch.disabled=busy||state.gamesPaused||!canSelectRocket()||!rocketUids.size||stake>Math.min(state.limits.max_stake,state.limits.max_payout/100);
    if($('#rocket-cash-value')) $('#rocket-cash-value').textContent=money(Math.round(game.stakeValue*Math.floor(value*100))/100);
    serverRocketFrame=requestAnimationFrame(frame);
  }
  serverRocketFrame=requestAnimationFrame(frame);
}
function depositDialog() {
  openModal(`<div class="modal-content"><h2>Пополнение</h2><form id="deposit-form" class="admin-form"><label>Брейнрот для депозита<select name="itemId">${ITEMS.filter(i=>i.value>=25).map(i=>`<option value="${i.id}">${esc(i.name)} · ${money(i.value)} BStars</option>`).join('')}</select></label><button class="primary">Создать заявку</button></form><p>Передай предмет владельцу в игре. BStars начислятся после подтверждения.</p><form id="stars-form" class="admin-form"><label>Telegram Stars<input name="stars" type="number" min="1" max="10000" step="1" required value="100"></label><p>1 Star = 1,5 BStars<br>После оплаты Stars вывод предметов ограничен на ${money(server.config.starsHoldHours/24)} дней. Игры и продажа внутри сайта доступны.</p>${server.config.paymentsEnabled ? `<label class="purchase-consent"><input type="checkbox" name="terms" required>Принимаю <a href="${esc(server.config.termsUrl)}" target="_blank" rel="noopener">условия покупки</a> и срок ограничения вывода</label><button class="primary">Оплатить звёздами</button>` : '<p>Оплата звёздами ещё не включена.</p>'}</form></div>`);
}
let withdrawUids=new Set();
function withdrawalDialog() {
  if(state.debt>0 || state.refundReviewPending || state.withdrawHeldUntil>server.now()) {
    openModal(`<div class="modal-content"><h2>Вывод временно ограничен</h2><p>${state.debt>0 ? `Задолженность: ${money(state.debt)} BStars. Обратись в поддержку.` : state.refundReviewPending ? 'Возврат Stars уточняется. Обратись в поддержку.' : `После оплаты Stars вывод доступен с ${new Date(state.withdrawHeldUntil).toLocaleString('ru-RU')}.`}</p><a class="secondary" href="${esc(server.config.ownerUrl)}" target="_blank" rel="noopener">Поддержка</a></div>`); return;
  }
  const eligible=state.inventory.filter(e=>['ketupat','garama','cerberus','dragon'].includes(e.itemId));
  withdrawUids=new Set();
  openModal(`<div class="modal-content"><h2>Вывод брейнротов</h2><p>Выбери предметы. До решения администратора они будут заблокированы.</p><div class="item-grid withdrawal-grid">${eligible.map(e=>itemCard(ITEM_BY_ID[e.itemId],{action:'withdraw-select',id:e.uid})).join('')}</div>${eligible.length ? '<button class="primary" data-action="withdraw-submit">Создать заявку</button>' : '<p>Для вывода нужны Ketupat Kepat, Garama, Cerberus или Dragon Cannelloni.</p>'}</div>`);
}
function ownerContact(requestId) {
  openModal(`<div class="modal-content"><h2>Заявка создана</h2><p>Номер: ${esc(requestId)}. Отправь его владельцу.</p><a class="primary" href="${esc(server.config.ownerUrl)}" target="_blank" rel="noopener">Открыть личные сообщения</a></div>`);
}
function enhanceServerProfile() {
  if (!state.isAdmin) $('.admin-link')?.remove();
  $('.storage-error')?.remove();
  if(state.debt || state.refundReviewPending || state.withdrawHeldUntil>server.now()) $('.profile-card').insertAdjacentHTML('afterend',`<p class="service-notice">${state.debt ? `Задолженность после возврата Stars: ${money(state.debt)} BStars. Обратись в поддержку.` : state.refundReviewPending ? 'Возврат Stars уточняется, вывод временно ограничен.' : `Вывод доступен с ${new Date(state.withdrawHeldUntil).toLocaleString('ru-RU')}.`}</p>`);
  $('.profile-card').insertAdjacentHTML('afterend',`<section class="history-panel"><details><summary>Проверка честности</summary><p class="proof-text">Server hash: ${esc(state.fair.serverHash)}<br>Client seed: ${esc(state.fair.clientSeed)}<br>Nonce: ${state.fair.nonce}</p><form id="fair-form" class="admin-form"><label>Новый client seed<input name="clientSeed" required maxlength="80" value="${esc(state.fair.clientSeed)}"></label><button class="secondary">Раскрыть старый seed и сменить</button></form></details></section><section class="history-panel"><h2>Заявки</h2>${state.transfers.filter(t=>!t.userId || t.userId===state.profile.id).map(t=>`<p class="proof-text">${t.kind==='deposit' ? 'Депозит' : 'Вывод'} · ${esc(t.id)} · ${{pending:'Ожидает',approved:'Подтверждена',rejected:'Отклонена'}[t.status] || esc(t.status)}</p>`).join('') || '<p class="proof-text">Заявок пока нет</p>'}</section>`);
}
function enhanceFinancialAdmin() {
  $('#main').insertAdjacentHTML('beforeend',`<section class="history-panel"><div class="selection-title"><h2>Контроль операций</h2></div><p class="proof-text">Бонусы сегодня: ${money(state.bonusSpentToday)} / ${money(state.limits.daily_bonus_budget)} BStars<br>Максимальная выплата: ${money(state.limits.max_payout)} BStars<br>Лимит активного риска: ${money(state.limits.max_open_risk)} BStars</p><div class="game-actions"><button class="secondary" data-action="admin-pause">${state.gamesPaused ? 'Возобновить ставки' : 'Приостановить новые ставки'}</button><button class="secondary" data-action="admin-backup">Скачать резервную копию</button></div><h2 style="margin-top:25px">Платежи Stars</h2>${(state.payments || []).map(p=>`<div class="admin-promo"><div><strong>${p.userId} · ${p.stars} Stars</strong><small>${esc(p.id)}<br>${{pending:'Счёт создан',processing:'Оплата начата',paid:'Оплачен',refund_requested:'Возврат уточняется',refunded:'Возвращён'}[p.status] || esc(p.status)}</small></div>${p.status==='paid' ? `<button class="secondary danger" data-action="refund-preview" data-id="${p.id}">Возврат</button>` : ''}</div>`).join('') || '<p class="proof-text">Платежей пока нет</p>'}</section>`);
}
async function downloadBackup() {
  try {const blob=await server.download('/api/admin/backup'), url=URL.createObjectURL(blob), link=document.createElement('a');link.href=url;link.download='freebie-backup.sqlite3';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);} catch(error){toast(error.message);}
}
async function pollServer() {
  if (!server || server.locked) return;
  try {
    if(!busy && !serverRequestPending) {
      const before=state, next=await server.request(`/api/state?limit=${Math.min(Math.max(state.history.length,200),5000)}`);
      if(!busy && !serverRequestPending) {
        adoptServerState(next);
        if($('#mine-timer') && state.mines?.status==='active') $('#mine-timer').textContent=`До завершения: ${Math.max(0,Math.ceil((state.mines.expiresAt-server.now())/1000))}с`;
        if(before.rocket?.status==='active' && state.rocket?.status!=='active' && state.rocket?.id===before.rocket.id) rocketResult();
        const financialChanged=JSON.stringify([before.inventory,before.balance,before.gamesPaused,before.debt,before.withdrawHeldUntil,before.refundReviewPending])!==JSON.stringify([state.inventory,state.balance,state.gamesPaused,state.debt,state.withdrawHeldUntil,state.refundReviewPending]);
        const flightChanged=JSON.stringify([before.round?.id,before.round?.ended,before.rocket?.status,before.mines])!==JSON.stringify([state.round?.id,state.round?.ended,state.rocket?.status,state.mines]);
        const changed=financialChanged || ['mines','rocket','cases'].includes(activeRoute) && flightChanged;
        const adminChanged=activeRoute==='admin' && JSON.stringify([before.payments,before.transfers,before.promos,before.bonusSpentToday])!==JSON.stringify([state.payments,state.transfers,state.promos,state.bonusSpentToday]);
        if((changed || adminChanged) && !$('#modal').open) {
          const values=[...document.querySelectorAll('#main input')].filter(i=>i.name && i.form?.id).map(i=>({form:i.form.id,name:i.name,value:i.value}));
          const focused=document.activeElement, focus=focused?.form?.id && focused.name ? {form:focused.form.id,name:focused.name} : null;
          render();for(const v of values){const input=document.getElementById(v.form)?.elements.namedItem(v.name);if(input)input.value=v.value;} if(focus)document.getElementById(focus.form)?.elements.namedItem(focus.name)?.focus({preventScroll:true});
        }
      }
    }
  } catch(error) { if(server.locked) {server.message=error.message;render();} }
  setTimeout(pollServer,600);
}
async function loadServerHistory() {
  historyLimit+=20;
  if(historyLimit>state.history.length && state.history.length<state.historyTotal) {
    try { const rows=await server.request(`/api/history?offset=${state.history.length}&limit=200`); state.history=[...new Map([...state.history,...rows].map(e=>[e.id,e])).values()]; } catch(error){toast(error.message);}
  }
  $('#operation-history').outerHTML=renderHistory(state,historyFilter,historyLimit,featureUI);
}
let currentProof=null;
async function showProof(id) {
  const entry=state.history.find(e=>e.id===id), proof=entry?.proof;
  if(!proof) return;
  let seed='', status='Seed ещё не раскрыт. Заверши мины и смени seed в профиле.', expected=proof.outcome;
  try {const data=await server.request(proof.roundId ? `/api/round/${proof.roundId}` : `/api/fair/reveal/${proof.serverHash}`); if(data.serverSeed)seed=data.serverSeed; if(proof.game==='rocket')expected=data.crash;} catch {}
  if(seed) {
    const checked=await verifyProof(proof,seed);
    if(!checked.valid) status=checked.detail;
    else {
      const draws=checked.draws; let result;
      if(proof.game==='case') { if(proof.table) {let cumulative=0;result=proof.table.find(d=>(cumulative+=d.chance)>draws[0])?.itemId || proof.table.at(-1).itemId;} else result=rollCase(CASE_BY_ID[proof.caseId],draws[0]); }
      else if(proof.game==='upgrade') result=upgradeLanding(proof.chance,draws[0],draws[1]);
      else if(proof.game==='slots') {let cursor=1;result=rollSlots(1,draws[0],()=>draws[cursor++]).symbols;}
      else if(proof.game==='mines') {const pool=Array.from({length:25},(_,i)=>i);result=Array.from({length:proof.bombCount},(_,i)=>pool.splice(Math.floor(draws[i]*pool.length),1)[0]);}
      else result=Math.min(100,draws[0]<.15 ? 1 : .85/(1-draws[0]));
      const match=proof.game==='upgrade' ? expected && expected.win===result.win && Math.abs(expected.x-result.x)<1e-8 && Math.abs(expected.y-result.y)<1e-8 : proof.game==='rocket' ? Math.abs(expected-result)<1e-8 : JSON.stringify(expected)===JSON.stringify(result);
      status=expected===undefined ? 'Хеш подтверждён. Для старой записи результат можно проверить независимым скриптом.' : match ? 'Хеш и результат подтверждены.' : 'Результат не совпадает с проверкой.';
    }
  }
  currentProof={...proof,serverSeed:seed,outcome:expected};
  openModal(`<div class="modal-content"><h2>Проверка результата</h2><p>${esc(status)}</p><details><summary>Данные проверки</summary><p class="proof-text">Server hash: ${esc(proof.serverHash)}<br>Server seed: ${esc(seed || 'Не раскрыт')}<br>Client seed: ${esc(proof.clientSeed)}<br>Nonce: ${proof.nonce}<br>Игра: ${esc(proof.game)}</p><p>HMAC-SHA256(server seed, client seed:nonce:cursor), первые 52 бита / 2⁵².</p><button class="secondary" data-action="copy-proof">Скопировать JSON проверки</button></details></div>`);
}
document.addEventListener('click', event => {
  const button = event.target.closest('[data-action]');
  if (button?.dataset.action === 'sound') {
    sound.setEnabled(!sound.enabled); updateSoundButton();
    try { localStorage.setItem('brainrot-freebie-sound',sound.enabled ? 'on' : 'off'); } catch {}
    sound.play('click'); return;
  }
  if (busy) { if (event.target.closest('a')) event.preventDefault(); return; }
  if (event.target.closest('button:not(:disabled),a,label.toggle')) sound.play('click');
  if (!button || button.disabled) return;
  const { action, id } = button.dataset;
  switch(action) {
    case 'admin-pause': void serverAction('admin-pause',{paused:!state.gamesPaused}).then(r=>{if(r)render();}); break;
    case 'admin-backup': void downloadBackup(); break;
    case 'refund-preview': {const payment=state.payments.find(p=>p.id===id);if(payment)openModal(`<div class="modal-content"><h2>Вернуть ${payment.stars} Stars?</h2><p>Telegram ID: ${payment.userId}. Выданные BStars будут списаны. Если они потрачены, появится задолженность и вывод будет заблокирован.</p><button class="primary" data-action="refund-confirm" data-id="${id}">Подтвердить возврат Stars</button></div>`);break;}
    case 'refund-confirm': void (async()=>{try{setBusy(true);const next=await server.request(`/api/admin/refund/${id}`,{});adoptServerState(next);closeModal();render();toast('Возврат подтверждён');}catch(error){toast(error.message);}finally{setBusy(false);}})(); break;
    case 'fair-proof': void showProof(id); break;
    case 'copy-proof': void navigator.clipboard.writeText(JSON.stringify(currentProof,null,2)).then(()=>toast('Данные проверки скопированы')).catch(()=>toast('Браузер не разрешил копирование')); break;
    case 'rocket-start': case 'rocket-cash': rocketAction(action); break;
    case 'select-rocket': if (canSelectRocket()) { rocketUids.has(id) ? rocketUids.delete(id) : rocketUids.add(id); render(); haptic(); } break;
    case 'rocket-clear': rocketUids.clear(); render(); break;
    case 'rocket-auto': rocketAuto=!rocketAuto; saveRocketPrefs(); render(); break;
    case 'rocket-preset': rocketAuto=true; rocketAutoTarget=Number(id); saveRocketPrefs(); render(); break;
    case 'mine-start': case 'mine-cell': case 'mine-cash': mineAction(action,id); break;
    case 'mine-count': if (state.mines?.status!=='active') { mineCount=Number(id); state.mines=null; persist(); render(); } break;
    case 'select-mine': if (state.mines?.status!=='active') { mineUids.has(id) ? mineUids.delete(id) : mineUids.add(id); render(); haptic(); } break;
    case 'mine-clear': mineUids.clear(); render(); break;
    case 'history-filter': historyFilter=id; historyLimit=20; $('#operation-history').outerHTML=renderHistory(state,historyFilter,historyLimit,featureUI); break;
    case 'history-more': if(server) { void loadServerHistory(); } else {historyLimit+=20; $('#operation-history').outerHTML=renderHistory(state,historyFilter,historyLimit,featureUI);} break;
    case 'toggle-promo': if(server) {void serverAction('admin-promo-toggle',{code:id}).then(r=>{if(r)render();});} else {try { state=togglePromo(state,id); persist(); render(); toast('Промокод обновлён'); } catch(error) { toast(error.message); }} break;
    case 'spin-slots': void spinSlots(); break;
    case 'select-slot': slotUid = slotUid === id ? null : id; render(); haptic(); break;
    case 'clear-slot': slotUid = null; render(); haptic(); break;
    case 'fast': fastMode = !fastMode; try { localStorage.setItem('brainrot-freebie-fast',fastMode ? 'on' : 'off'); } catch {} button.setAttribute('aria-pressed',String(fastMode)); haptic(); break;
    case 'open-case': void openCase(id); break;
    case 'upgrade': void upgrade(); break;
    case 'select-source': sourceUids.has(id) ? sourceUids.delete(id) : sourceUids.add(id); quick = null; render(); haptic(); break;
    case 'clear-source': sourceUids.clear(); quick = null; render(); haptic(); break;
    case 'select-target': targetId = id; quick = null; render(); haptic(); break;
    case 'quick': quickTarget(id); break;
    case 'sell': sellDialog(id); break;
    case 'confirm-sell': sell(id); break;
    case 'topup': topup(); break;
    case 'withdraw': if(server) withdrawalDialog(); else openModal('<div class="modal-content"><div class="modal-status-icon">↗</div><h2>Вывод</h2><p>Вывод пока недоступен.</p><div class="modal-actions"><button class="primary" data-action="close-modal">Понятно</button></div></div>'); break;
    case 'withdraw-select': withdrawUids.has(id) ? withdrawUids.delete(id) : withdrawUids.add(id); button.classList.toggle('selected',withdrawUids.has(id)); button.setAttribute('aria-pressed',String(withdrawUids.has(id))); break;
    case 'withdraw-submit': void serverAction('withdraw',{uids:[...withdrawUids]}).then(r=>{if(r){render();ownerContact(r.result.requestId);}}); break;
    case 'transfer-approve': case 'transfer-reject': void serverAction('admin-transfer',{requestId:id,decision:action==='transfer-approve' ? 'approve' : 'reject'}).then(r=>{if(r)render();}); break;
    case 'balance': if(server) depositDialog(); else openModal(`<div class="modal-content"><h2>Баланс</h2><div class="result-value">✦ ${money(state.balance)} BStars</div><div class="modal-actions"><button class="primary" data-action="topup">Пополнить +100</button><button class="secondary" data-action="goto-profile">В профиль</button></div></div>`); break;
    case 'goto-profile': closeModal(); location.hash = 'profile'; break;
    case 'goto-cases': closeModal(); location.hash = 'cases'; break;
    case 'to-upgrade': sourceUids = new Set([id]); targetId = null; closeModal(); if (parseRoute() === 'upgrade') render(); else location.hash = 'upgrade'; break;
    case 'close-modal': closeModal(); break;
    case 'keep-drop': closeModal(); break;
    case 'case-odds': fairness(id); break;
  }
});
document.addEventListener('input', event => {
  if (event.target.id === 'target-search' && !busy) { targetSearch = event.target.value; $('#target-grid').innerHTML = targetsMarkup(); }
  if (event.target.id==='rocket-auto-value' && !busy) { const value=Number(event.target.value); if (value>=1.01 && value<=100 && Number.isFinite(value)) { rocketAutoTarget=value; saveRocketPrefs(); } }
});
document.addEventListener('submit', async event => {
  const formId=event.target.id;
  if (!['promo-form','admin-balance-form','admin-promo-form','deposit-form','stars-form','fair-form'].includes(formId)) return;
  event.preventDefault(); if (busy) return;
  const data=new FormData(event.target);
  if (server) {
    if(formId==='stars-form') {
      try {setBusy(true); const invoice=await server.request('/api/invoice',{stars:Number(data.get('stars')),termsAccepted:data.get('terms')==='on'},crypto.randomUUID()); tg.openInvoice(invoice.url);} catch(error){toast(error.message);} finally{setBusy(false);} return;
    }
    const action=formId==='promo-form' ? 'promo' : formId==='admin-promo-form' ? 'admin-promo' : formId==='admin-balance-form' ? 'admin-balance' : formId==='deposit-form' ? 'deposit' : 'fair-rotate';
    const body=formId==='promo-form' ? {code:data.get('promo')} : formId==='admin-promo-form' ? {code:data.get('code'),reward:Number(data.get('reward')),limit:Number(data.get('limit'))} : formId==='admin-balance-form' ? {userId:Number(data.get('userId')),amount:Number(data.get('amount')),direction:event.submitter?.value || 'add',reason:data.get('reason')} : formId==='deposit-form' ? {itemId:data.get('itemId')} : {clientSeed:data.get('clientSeed')};
    const response=await serverAction(action,body);
    if(response) {render(); if(formId==='deposit-form') ownerContact(response.result.requestId); else if(formId==='fair-form') openModal(`<div class="modal-content"><h2>Раскрытый server seed</h2><p class="proof-text">Hash: ${esc(response.result.serverHash)}<br>Seed: ${esc(response.result.serverSeed)}</p><p>Проверка доступна в истории операций.</p></div>`); else toast('Операция выполнена');} return;
  }
  try {
    if (formId==='promo-form') { const before=state.balance; state=redeemPromo(state,data.get('promo')); toast(`Промокод активирован! +${money(state.balance-before)} BStars`); notifyHaptic(true); }
    else if (formId==='admin-promo-form') { state=createPromo(state,data.get('code'),Number(data.get('reward')),Number(data.get('limit'))); toast('Промокод создан'); }
    else { state=adjustBalance(state,Number(data.get('amount')),event.submitter?.value || 'add',data.get('reason')); toast('Баланс обновлён'); }
    persist(); render();
  } catch(error) { toast(error.message); }
});
persist(); render();
if(server && !server.locked) void pollServer();

