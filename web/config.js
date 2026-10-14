// Runtime containers only. Gameplay data is supplied by authenticated /api/catalog.
export const SETTINGS = { storageKey: 'brainrot-freebie-v1', startingBalance: 0, rtp: null };
export const SLOT_RULES = {};
export const ITEMS = [];
export const ITEM_BY_ID = {};
export const CASES = [];
export const CASE_BY_ID = {};
export const RARITIES = {};

export function applyCatalog(catalog) {
  if (!catalog || !Array.isArray(catalog.items) || !catalog.items.length || !Array.isArray(catalog.cases) ||
      !catalog.settings || !Number.isFinite(catalog.settings.rtp) || catalog.settings.rtp<=0 || catalog.settings.rtp>1 ||
      !catalog.slotRules || !catalog.rarities) throw new Error('Сервер не передал игровой каталог');
  const ids=new Set(catalog.items.map(i=>i.id));
  if(ids.size!==catalog.items.length || catalog.items.some(i=>typeof i.id!=='string' || !i.id ||
      typeof i.name!=='string' || !Number.isFinite(i.value) || i.value<=0 || typeof i.image!=='string') ||
      new Set(catalog.cases.map(c=>c.id)).size!==catalog.cases.length ||
      catalog.cases.some(c=>typeof c.id!=='string' || !c.id || !Number.isFinite(c.price) || c.price<0 ||
        !Array.isArray(c.drops) || !c.drops.length || c.drops.some(d=>!ids.has(d.itemId) || !Number.isFinite(d.baseChance) || d.baseChance<0) ||
        Math.abs(c.drops.reduce((n,d)=>n+d.baseChance,0)-1)>1e-9))
    throw new Error('Некорректный игровой каталог сервера');
  ITEMS.splice(0,ITEMS.length,...catalog.items);
  CASES.splice(0,CASES.length,...catalog.cases);
  for(const [target,values] of [[ITEM_BY_ID,Object.fromEntries(ITEMS.map(i=>[i.id,i]))],
      [CASE_BY_ID,Object.fromEntries(CASES.map(c=>[c.id,c]))],[RARITIES,catalog.rarities],[SLOT_RULES,catalog.slotRules]]) {
    Object.keys(target).forEach(key=>delete target[key]);Object.assign(target,values);
  }
  SETTINGS.rtp=catalog.settings.rtp;
}
