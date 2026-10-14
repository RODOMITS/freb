import { SETTINGS, ITEM_BY_ID, ITEMS, SLOT_RULES } from './config.js';

// Catalog weights are the final probabilities used by both client and server.
export function distribution(caseConfig) {
  const drops = caseConfig.drops;
  const total = drops.reduce((sum, drop) => sum + drop.baseChance, 0);
  if (Math.abs(total - 1) > 1e-9 || drops.some(drop => drop.baseChance < 0)) throw new Error('Case chances must total 100%');
  return drops.map(drop => ({...drop, chance:drop.baseChance}));
}
export function randomUnit() {
  const n = new Uint32Array(1);
  globalThis.crypto.getRandomValues(n);
  return n[0] / 4294967296;
}
export function rollCase(caseConfig, unit = randomUnit()) {
  if (unit < 0 || unit >= 1) throw new Error('Random unit must be in [0, 1)');
  const drops = distribution(caseConfig);
  let cumulative = 0;
  return drops.find(d => (cumulative += d.chance) > unit)?.itemId || drops.at(-1).itemId;
}
export function upgradeChance(source, target) {
  return source && target && target.value > source.value ? SETTINGS.rtp * source.value / target.value : 0;
}
export function buildUpgradeStake(inventory, selectedUids) {
  const ids = new Set(selectedUids);
  const entries = inventory.filter(entry => ids.has(entry.uid));
  if (entries.length !== ids.size || entries.some(entry => !ITEM_BY_ID[entry.itemId])) throw new Error('Selected items are not available');
  return { entries, value: entries.reduce((sum,entry) => sum+ITEM_BY_ID[entry.itemId].value,0), remaining: inventory.filter(entry => !ids.has(entry.uid)) };
}
// The filled boundary is calibrated to the arrow's path around the circle.
export function liquidLevel(chance) {
  if (!Number.isFinite(chance) || chance < 0 || chance > 1) throw new Error('Invalid probability');
  return 120 + Math.cos(Math.PI * chance) * 104;
}
export function upgradeLanding(chance, radialUnit = randomUnit(), angleUnit = randomUnit()) {
  if (![radialUnit, angleUnit].every(n => Number.isFinite(n) && n >= 0 && n < 1)) throw new Error('Invalid random unit');
  const angle = angleUnit * Math.PI * 2;
  const x = 120 + Math.sin(angle) * 104;
  const y = 120 - Math.cos(angle) * 104;
  return {x, y, angle:angleUnit*360, level:liquidLevel(chance), win:chance>0 && y>=liquidLevel(chance)};
}
function legacyLiquidLevel(chance) {
  if (!Number.isFinite(chance) || chance < 0 || chance > 1) throw new Error('Invalid probability');
  let low = -1, high = 1;
  for (let i = 0; i < 40; i++) {
    const y = (low + high) / 2;
    const area = (Math.acos(y) - y * Math.sqrt(1 - y * y)) / Math.PI;
    if (area > chance) low = y; else high = y;
  }
  return 120 + (low + high) / 2 * 104;
}
export function legacyUpgradeLanding(chance, radialUnit = randomUnit(), angleUnit = randomUnit()) {
  if (![radialUnit, angleUnit].every(n => Number.isFinite(n) && n >= 0 && n < 1)) throw new Error('Invalid random unit');
  const radius = Math.sqrt(radialUnit) * 104;
  const angle = angleUnit * Math.PI * 2;
  const x = 120 + Math.sin(angle) * radius;
  const y = 120 - Math.cos(angle) * radius;
  return { x, y, angle: angleUnit * 360, win: chance > 0 && y >= legacyLiquidLevel(chance) };
}
export function slotMultiplier(symbols) {
  if (!Array.isArray(symbols) || symbols.length !== 3 || symbols.some(id => !ITEM_BY_ID[id])) throw new Error('Invalid slot symbols');
  const unique = new Set(symbols).size;
  return unique === 1 ? SLOT_RULES.tripleMultiplier : unique === 2 ? SLOT_RULES.pairMultiplier : 0;
}
export function rollSlots(betValue, unit = randomUnit(), draw = randomUnit, rules = SLOT_RULES, itemIds = ITEMS.map(item=>item.id)) {
  if (!Number.isSafeInteger(betValue) || betValue <= 0 || !Number.isFinite(unit) || unit < 0 || unit >= 1) throw new Error('Invalid slot bet or random unit');
  const pool = [...itemIds];
  function pick(list) {
    const n = draw();
    if (!Number.isFinite(n) || n < 0 || n >= 1) throw new Error('Invalid random unit');
    return list.splice(Math.floor(n*list.length),1)[0];
  }
  const a = pick(pool), b = pick(pool), c = pick(pool);
  const symbols = unit < rules.tripleChance ? [a,a,a] : unit < rules.tripleChance+rules.pairChance ? [a,a,b] : [a,b,c];
  const shuffled = [];
  while (symbols.length) shuffled.push(pick(symbols));
  const multiplier = slotMultiplier(shuffled);
  return { symbols:shuffled, multiplier, betValue, payout:betValue*multiplier };
}
export function settleSlots(state, uid, unit = randomUnit(), draw = randomUnit) {
  const bet = state.inventory.find(entry => entry.uid === uid);
  if (!bet || !ITEM_BY_ID[bet.itemId]) throw new Error('Selected item is not available');
  const result = rollSlots(ITEM_BY_ID[bet.itemId].value,unit,draw);
  return { ...state, balance:state.balance+result.payout, inventory:state.inventory.filter(entry=>entry.uid!==uid), slotResult:result };
}
export function newState() { return { version: 1, balance: SETTINGS.startingBalance, inventory: [], promoUsed: false, promos:[], redeemed:[], history:[], mines:null, rocket:null, stats: { opened: 0, upgrades: 0, wins: 0 }, feed: [], slotResult:null }; }
export function validateState(value) {
  if (!value || value.version !== 1 || !Number.isFinite(value.balance) || value.balance < 0 || !Array.isArray(value.inventory)) return newState();
  const inventory = value.inventory.filter(x => x && ITEM_BY_ID[x.itemId] && typeof x.uid === 'string');
  let slotResult = null;
  try {
    const result = value.slotResult;
    if (result && result.multiplier === slotMultiplier(result.symbols) && Number.isSafeInteger(result.betValue) && result.betValue > 0 && result.payout === result.betValue*result.multiplier) slotResult = {symbols:result.symbols,multiplier:result.multiplier,betValue:result.betValue,payout:result.payout};
  } catch {}
  const promos = Array.isArray(value.promos) ? [...new Map(value.promos.filter(p=>validPromo(p)).map(p=>[p.code,{code:p.code,reward:p.reward,limit:p.limit,used:p.used,active:p.active!==false}])).values()] : newState().promos.map(p=>({...p,used:value.promoUsed ? 1 : 0}));
  const redeemed = [...new Set((Array.isArray(value.redeemed) ? value.redeemed : value.promoUsed ? [SETTINGS.promo] : []).filter(code=>typeof code==='string' && /^[A-Z0-9_-]{3,30}$/.test(code)))];
  const history = Array.isArray(value.history) ? value.history.filter(h=>h && typeof h.id==='string' && typeof h.title==='string' && typeof h.detail==='string' && Number.isFinite(h.delta) && typeof h.createdAt==='string' && Number.isFinite(Date.parse(h.createdAt))).slice(0,200) : [];
  const mines = validMines(value.mines) ? value.mines : null;
  const rocket=validRocket(value.rocket) ? value.rocket : null;
  return { ...newState(), balance: Math.round(value.balance*100)/100, inventory: [...new Map(inventory.map(x => [x.uid, x])).values()], promoUsed: value.promoUsed === true, promos, redeemed, history, mines, rocket,
    stats: Object.fromEntries(['opened', 'upgrades', 'wins'].map(key => [key, Number.isSafeInteger(value.stats?.[key]) && value.stats[key] >= 0 ? value.stats[key] : 0])),
    feed: Array.isArray(value.feed) ? value.feed.filter(x => ITEM_BY_ID[x?.itemId]).slice(0, 12) : [], slotResult };
}

function operationId() { return globalThis.crypto.randomUUID?.() || `${Date.now()}-${Math.floor(randomUnit()*1e12)}`; }
export function recordOperation(state, operation) {
  const entry = {id:operationId(),type:'wallet',status:'done',delta:0,detail:'',createdAt:new Date().toISOString(),...operation};
  return {...state,history:[entry,...(state.history || [])].slice(0,200)};
}
function validPromo(p) { return p && typeof p.code==='string' && /^[A-Z0-9_-]{3,30}$/.test(p.code) && Number.isSafeInteger(p.reward) && p.reward>0 && p.reward<=1000000 && Number.isSafeInteger(p.limit) && p.limit>0 && p.limit<=1000000 && Number.isSafeInteger(p.used) && p.used>=0 && p.used<=p.limit; }
export function createPromo(state, code, reward, limit) {
  const promo = {code:String(code).trim().toUpperCase(),reward,limit,used:0,active:true};
  if (!validPromo(promo)) throw new Error('Код: 3–30 букв A–Z, цифр, дефисов или _. Награда и лимит: целые числа от 1 до 1 000 000.');
  if (state.promos.some(p=>p.code===promo.code)) throw new Error('Такой промокод уже существует.');
  return recordOperation({...state,promos:[promo,...state.promos]},{type:'admin',title:'Создан промокод',detail:`${promo.code} · ${reward} BStars · активаций: ${limit}`});
}
export function redeemPromo(state, code) {
  const normalized = String(code).trim().toUpperCase();
  const promo = state.promos.find(p=>p.code===normalized);
  if (!promo || !promo.active) throw new Error('Промокод не найден или отключён.');
  if (state.redeemed.includes(normalized)) throw new Error('Ты уже активировал этот промокод.');
  if (promo.used>=promo.limit) throw new Error('Лимит активаций исчерпан.');
  return recordOperation({...state,balance:state.balance+promo.reward,promos:state.promos.map(p=>p.code===normalized ? {...p,used:p.used+1} : p),redeemed:[...state.redeemed,normalized],promoUsed:state.promoUsed || normalized===SETTINGS.promo},{type:'promo',title:'Промокод активирован',detail:normalized,delta:promo.reward});
}
export function togglePromo(state, code) {
  const promo = state.promos.find(p=>p.code===code);
  if (!promo) throw new Error('Промокод не найден.');
  return recordOperation({...state,promos:state.promos.map(p=>p.code===code ? {...p,active:!p.active} : p)},{type:'admin',title:promo.active ? 'Промокод отключён' : 'Промокод включён',detail:code});
}
export function adjustBalance(state, amount, direction, reason='') {
  if (!Number.isSafeInteger(amount) || amount<=0 || amount>1000000 || !['add','remove'].includes(direction)) throw new Error('Введи целую сумму от 1 до 1 000 000.');
  const delta = direction==='add' ? amount : -amount;
  if (state.balance+delta<0) throw new Error('Списание превышает баланс.');
  return recordOperation({...state,balance:Math.round((state.balance+delta)*100)/100},{type:'admin',title:delta>0 ? 'Начисление администратором' : 'Списание администратором',detail:String(reason).trim().slice(0,120) || 'Изменение баланса',delta});
}
export function minesMultiplier(bombs, opened, rtp = SETTINGS.rtp) {
  if (![3,5,10].includes(bombs) || !Number.isInteger(opened) || opened<0 || opened>25-bombs) throw new Error('Некорректные параметры мин.');
  if (!opened) return 0;
  let survival = 1;
  for (let i=0;i<opened;i++) survival *= (25-bombs-i)/(25-i);
  return rtp/survival;
}
export function minesPayout(game) { return Math.round(game.stakeValue*minesMultiplier(game.bombCount,game.opened.length,game.rtp || SETTINGS.rtp)*100)/100; }
function validMines(game) {
  if (!game) return false;
  return typeof game.id==='string' && ['active','lost','won'].includes(game.status) && [3,5,10].includes(game.bombCount) && Array.isArray(game.bombs) && game.bombs.length===game.bombCount && new Set(game.bombs).size===game.bombCount && game.bombs.every(n=>Number.isInteger(n)&&n>=0&&n<25) && Array.isArray(game.opened) && new Set(game.opened).size===game.opened.length && game.opened.every(n=>Number.isInteger(n)&&n>=0&&n<25&&!game.bombs.includes(n)) && Number.isSafeInteger(game.stakeValue) && game.stakeValue>0 && Number.isFinite(game.payout) && game.payout>=0 && (game.status==='lost' ? game.bombs.includes(game.hit) : true);
}
export function startMines(state, selectedUids, bombCount, draw=randomUnit) {
  if (state.mines?.status==='active') throw new Error('Сначала заверши текущую игру.');
  if (![3,5,10].includes(bombCount)) throw new Error('Выбери 3, 5 или 10 мин.');
  const stake = buildUpgradeStake(state.inventory,selectedUids);
  if (!stake.entries.length) throw new Error('Выбери предметы для ставки.');
  const pool = Array.from({length:25},(_,index)=>index), bombs=[];
  for (let i=0;i<bombCount;i++) { const unit=draw(); if (!Number.isFinite(unit)||unit<0||unit>=1) throw new Error('Invalid random unit'); bombs.push(pool.splice(Math.floor(unit*pool.length),1)[0]); }
  const game = {id:operationId(),bombCount,bombs,opened:[],stakeValue:stake.value,stakeCount:stake.entries.length,status:'active',payout:0,hit:null};
  return recordOperation({...state,inventory:stake.remaining,mines:game},{id:game.id,type:'mines',title:'Мины',status:'pending',detail:`Ставка: ${stake.value} BStars · предметов: ${stake.entries.length} · мин: ${bombCount}`});
}
function finishMines(state, game) {
  return {...state,balance:Math.round((state.balance+game.payout)*100)/100,mines:game,history:state.history.map(entry=>entry.id===game.id ? {...entry,status:game.status==='won' ? 'win' : 'lose',delta:game.payout,detail:`Ставка: ${game.stakeValue} BStars · открыто: ${game.opened.length} · ${game.status==='won' ? `выигрыш: ${game.payout} BStars` : 'попадание на мину'}`} : entry)};
}
export function revealMine(state, index) {
  const game = state.mines;
  if (!game || game.status!=='active') throw new Error('Нет активной игры.');
  if (!Number.isInteger(index)||index<0||index>=25||game.opened.includes(index)) throw new Error('Клетка недоступна.');
  if (game.bombs.includes(index)) return finishMines(state,{...game,status:'lost',hit:index,payout:0});
  const updated = {...game,opened:[...game.opened,index]};
  if (updated.opened.length===25-game.bombCount) return finishMines(state,{...updated,status:'won',payout:minesPayout(updated)});
  return {...state,mines:updated};
}
export function cashMines(state) {
  const game=state.mines;
  if (!game || game.status!=='active' || !game.opened.length) throw new Error('Открой хотя бы одну безопасную клетку.');
  return finishMines(state,{...game,status:'won',payout:minesPayout(game)});
}

export const ROCKET_RULES = {max:100,growth:.24,countdownMs:1200};
export function rocketOutcome(unit=randomUnit()) {
  if (!Number.isFinite(unit)||unit<0||unit>=1) throw new Error('Invalid random unit');
  const raw=unit<1-SETTINGS.rtp ? 1 : SETTINGS.rtp/(1-unit);
  return {crash:Math.min(raw,ROCKET_RULES.max),capped:raw>=ROCKET_RULES.max};
}
export function rocketValue(game,now=Date.now()) {
  return Math.min(game.crash,Math.exp(Math.max(0,now-game.startAt)/1000*ROCKET_RULES.growth));
}
export function rocketFinished(game,now=Date.now()) { return now>=game.startAt+Math.log(game.crash)/ROCKET_RULES.growth*1000; }
function validRocket(game) {
  return game && typeof game.id==='string' && ['active','won','lost'].includes(game.status) && Number.isFinite(game.startAt) && Number.isFinite(game.crash) && game.crash>=1 && game.crash<=100 && typeof game.capped==='boolean' && Number.isSafeInteger(game.stakeValue) && game.stakeValue>0 && Number.isFinite(game.payout) && game.payout>=0 && (game.autoCash===null || Number.isFinite(game.autoCash)&&game.autoCash>=1.01&&game.autoCash<=100) && Number.isFinite(game.cashAt) && game.cashAt>=0&&game.cashAt<=100;
}
export function startRocket(state,selectedUids,autoCash=null,unit=randomUnit(),now=Date.now(),amount=null) {
  state=advanceRocket(state,now);
  if (state.rocket && !rocketFinished(state.rocket,now)) throw new Error('Дождись завершения полёта.');
  if (autoCash!==null && (!Number.isFinite(autoCash)||autoCash<1.01||autoCash>100||Math.abs(autoCash*100-Math.round(autoCash*100))>1e-8)) throw new Error('Автозабор: от ×1,01 до ×100,00, максимум два знака после запятой.');
  let stake,balance=state.balance;
  if(amount!==null) {
    if(!Number.isFinite(amount)||amount<.01||Math.abs(amount*100-Math.round(amount*100))>1e-7||selectedUids.size)throw new Error('Укажи ставку с баланса от 0,01 BStars, до двух знаков.');
    if(Math.round(amount*100)>Math.round(balance*100))throw new Error('Не хватает BStars.');
    amount=Math.round(amount*100)/100;balance=Math.round((balance-amount)*100)/100;
    stake={value:amount,entries:[],remaining:state.inventory};
  } else {
    stake=buildUpgradeStake(state.inventory,selectedUids);
    if(!stake.entries.length)throw new Error('Выбери предметы или укажи ставку с баланса.');
  }
  const outcome=rocketOutcome(unit);
  const game={id:operationId(),...outcome,startAt:now+ROCKET_RULES.countdownMs,stakeValue:stake.value,stakeCount:stake.entries.length,autoCash,status:'active',payout:0,cashAt:0,automatic:false};
  return recordOperation({...state,balance,inventory:stake.remaining,rocket:game},{id:game.id,type:'rocket',title:'Ракетка',status:'pending',detail:`Ставка: ${stake.value} BStars · ${amount!==null ? 'с баланса' : 'предметов: '+stake.entries.length}${autoCash ? ` · автозабор ×${autoCash}` : ''}`});
}
function finishRocket(state,game,status,multiplier,automatic) {
  const payout=status==='won' ? Math.round(game.stakeValue*multiplier*100)/100 : 0;
  const updated={...game,status,payout,cashAt:multiplier,automatic};
  const operation={id:game.id,type:'rocket',title:'Ракетка',status:status==='won' ? 'win' : 'lose',delta:payout,detail:`Ставка: ${game.stakeValue} BStars · ${status==='won' ? `${automatic ? 'автозабор' : 'забор'} ×${multiplier.toFixed(2)} · выплата ${payout} BStars` : `взрыв ×${(Math.floor(game.crash*100)/100).toFixed(2)}`}`};
  const next={...state,rocket:updated,balance:Math.round((state.balance+payout)*100)/100};
  return state.history.some(entry=>entry.id===game.id) ? {...next,history:state.history.map(entry=>entry.id===game.id ? {...entry,...operation} : entry)} : recordOperation(next,operation);
}
export function advanceRocket(state,now=Date.now()) {
  const game=state.rocket;
  if (!game || game.status!=='active' || now<game.startAt) return state;
  const value=rocketValue(game,now);
  if (game.autoCash!==null && game.autoCash<=game.crash && value>=game.autoCash) return finishRocket(state,game,'won',game.autoCash,true);
  if (rocketFinished(game,now)) return game.capped ? finishRocket(state,game,'won',100,true) : finishRocket(state,game,'lost',0,false);
  return state;
}
export function cashRocket(state,now=Date.now()) {
  const reconciled=advanceRocket(state,now), game=reconciled.rocket;
  if (reconciled!==state) return reconciled; // scheduled auto-cash/crash wins a delayed click
  if (!game || game.status!=='active') throw new Error('Ставка уже завершена.');
  if (now<game.startAt) throw new Error('Дождись старта ракеты.');
  return finishRocket(state,game,'won',Math.floor(rocketValue(game,now)*100)/100,false);
}
