import assert from 'node:assert/strict';
import { SETTINGS, SLOT_RULES, ITEMS, CASES, ITEM_BY_ID, CASE_BY_ID, RARITIES, applyCatalog } from '../web/config.js';

assert.equal(ITEMS.length,0);
assert.equal(CASES.length,0);
assert.equal(SETTINGS.rtp,null);
assert.equal(SETTINGS.startingBalance,0);
assert.deepEqual(SLOT_RULES,{});
assert.throws(()=>applyCatalog(null));
const catalog={
  items:[{id:'server-item',name:'С сервера',value:127,image:'img/server.webp',rarity:'rare'}],
  cases:[{id:'server-case',name:'Серверный кейс',price:50,drops:[{itemId:'server-item',baseChance:1}]}],
  settings:{rtp:.73},
  slotRules:{pairChance:.29,tripleChance:.03,pairMultiplier:2,tripleMultiplier:5},
  rarities:{rare:'Редкий'}
};
const itemsRef=ITEMS,caseMapRef=CASE_BY_ID;
applyCatalog(catalog);
assert.equal(ITEMS,itemsRef);
assert.equal(CASE_BY_ID,caseMapRef);
assert.equal(ITEM_BY_ID['server-item'].value,127);
assert.equal(CASE_BY_ID['server-case'].price,50);
assert.equal(SETTINGS.rtp,.73);
assert.equal(SLOT_RULES.pairChance,.29);
assert.equal(RARITIES.rare,'Редкий');
assert.throws(()=>applyCatalog({...catalog,settings:{rtp:0}}));
assert.throws(()=>applyCatalog({...catalog,cases:[{...catalog.cases[0],drops:[{itemId:'missing',baseChance:1}]}]}));
assert.equal(CASE_BY_ID['server-case'].price,50);
const next={...catalog,items:[{...catalog.items[0],id:'replacement',value:900}],cases:[{...catalog.cases[0],id:'replacement-case',price:300,drops:[{itemId:'replacement',baseChance:1}]}]};
applyCatalog(next);
assert.equal(ITEM_BY_ID['server-item'],undefined);
assert.equal(CASE_BY_ID['server-case'],undefined);
assert.equal(ITEM_BY_ID.replacement.value,900);
console.log('Server catalog contract: passed');
