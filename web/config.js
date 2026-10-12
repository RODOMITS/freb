// All economy, asset paths and case contents live here. BStars are demo coins.
export const SETTINGS = { rtp: 0.85, startingBalance: 500, topUp: 100, promo: 'MIAMI', promoReward: 100, storageKey: 'brainrot-freebie-v1' };
export const SLOT_RULES = { pairChance: 0.35, tripleChance: 0.03, pairMultiplier: 2, tripleMultiplier: 5 };
const definitions = [
  ['67', '67', 3, 'common'],
  ['lagrand', 'La Grande Combinasione', 7, 'common'],
  ['bananito', 'Bananito', 9, 'common'],
  ['esok', 'Esok Sekolah', 15, 'common'],
  ['ketupat', 'Ketupat Kepat', 25, 'rare'],
  ['tictac', 'Tictac Sahur', 42, 'rare'],
  ['lavadorito', 'Lavadorito Spinito', 60, 'rare'],
  ['garama', 'Garama and Madundung', 72, 'rare'],
  ['eviledon', 'Eviledon', 85, 'epic'],
  ['cash', 'Cash or Card', 146, 'epic'],
  ['pizza', 'Pizza and Ranch', 154, 'epic'],
  ['burguro', 'Burguro and Fryuro', 171, 'epic'],
  ['capitano', 'Capitano Moby', 200, 'epic'],
  ['cerberus', 'Cerberus', 214, 'legendary'],
  ['pegasus', 'Celestial Pegasus', 250, 'legendary'],
  ['guest666', 'Guest666', 257, 'legendary'],
  ['cookie', 'Cookie and Milki', 385, 'legendary'],
  ['fortunu', 'Fortunu and Cashuru', 599, 'legendary'],
  ['ketupatbro', 'Ketupat Bros', 771, 'secret'],
  ['foxini', 'Foxini Lanterini', 857, 'secret'],
  ['venuspino', 'Venuspino', 900, 'secret'],
  ['dragon', 'Dragon Cannelloni', 942, 'secret'],
];
export const ITEMS = definitions.map(([id, name, value, rarity, asset]) => ({ id, name, value, rarity, image: `img/brainrots/${asset || id}.webp` }));
export const ITEM_BY_ID = Object.fromEntries(ITEMS.map(item => [item.id, item]));
export const RARITIES = { common: 'Обычный', rare: 'Редкий', epic: 'Эпический', legendary: 'Легендарный', secret: 'Секретный' };
const weights = [48, 27, 15, 7, 2.5, 0.5];
const makeCase = (id, name, price, subtitle, hue, tag, ids) => ({ id, name, price, subtitle, hue, tag, image: 'img/cases/plant.png', drops: ids.map((itemId, i) => ({ itemId, baseChance: weights[i] / 100 })) });
export const CASES = [
  makeCase('plant', 'Plant Party', 50, 'Маленький кейс. Большой вайб.', 0, 'STARTER', ['bananito', 'foxini', 'burguro', 'capitano', 'venuspino', 'cerberus']),
  makeCase('ocean', 'Ocean Drive', 100, 'Поймай свою волну удачи.', 90, 'FRESH', ['foxini', 'burguro', 'lavadorito', 'ketupatbro', 'dragon', 'garama']),
  makeCase('miami', 'Miami Vice', 250, 'Ночь, неон и редкие находки.', 200, 'HOT', ['esok', 'capitano', 'venuspino', 'dragon', 'tictac', 'guest666']),
  makeCase('sunset', 'Golden Hour', 500, 'Для тех, кто целится выше.', 310, 'PREMIUM', ['capitano', 'ketupatbro', 'dragon', 'fortunu', 'guest666', 'eviledon']),
];
CASES.push(...[
  {
    "id": "sahur",
    "name": "Sahur",
    "price": 19,
    "subtitle": "",
    "hue": 0,
    "tag": "",
    "image": "img/cases/sahur.png",
    "drops": [
      {
        "itemId": "67",
        "baseChance": 0.16666666666666666
      },
      {
        "itemId": "lagrand",
        "baseChance": 0.16666666666666666
      },
      {
        "itemId": "bananito",
        "baseChance": 0.16666666666666666
      },
      {
        "itemId": "esok",
        "baseChance": 0.16666666666666666
      },
      {
        "itemId": "ketupat",
        "baseChance": 0.16666666666666666
      },
      {
        "itemId": "tictac",
        "baseChance": 0.16666666666666666
      }
    ]
  },
  {
    "id": "fastfood",
    "name": "Fastfood",
    "price": 49,
    "subtitle": "",
    "hue": 0,
    "tag": "",
    "image": "img/cases/fastfood.png",
    "drops": [
      {
        "itemId": "bananito",
        "baseChance": 0.16666666666666666
      },
      {
        "itemId": "esok",
        "baseChance": 0.16666666666666666
      },
      {
        "itemId": "ketupat",
        "baseChance": 0.16666666666666666
      },
      {
        "itemId": "cash",
        "baseChance": 0.16666666666666666
      },
      {
        "itemId": "pizza",
        "baseChance": 0.16666666666666666
      },
      {
        "itemId": "burguro",
        "baseChance": 0.16666666666666666
      }
    ]
  },
  {
    "id": "cash",
    "name": "Cash",
    "price": 99,
    "subtitle": "",
    "hue": 0,
    "tag": "",
    "image": "img/cases/cash.png",
    "drops": [
      {
        "itemId": "ketupat",
        "baseChance": 0.16666666666666666
      },
      {
        "itemId": "lavadorito",
        "baseChance": 0.16666666666666666
      },
      {
        "itemId": "garama",
        "baseChance": 0.16666666666666666
      },
      {
        "itemId": "cash",
        "baseChance": 0.16666666666666666
      },
      {
        "itemId": "cookie",
        "baseChance": 0.16666666666666666
      },
      {
        "itemId": "fortunu",
        "baseChance": 0.16666666666666666
      }
    ]
  },
  {
    "id": "olympus",
    "name": "Olympus",
    "price": 249,
    "subtitle": "",
    "hue": 0,
    "tag": "",
    "image": "img/cases/olympus.png",
    "drops": [
      {
        "itemId": "eviledon",
        "baseChance": 0.16666666666666666
      },
      {
        "itemId": "capitano",
        "baseChance": 0.16666666666666666
      },
      {
        "itemId": "cerberus",
        "baseChance": 0.16666666666666666
      },
      {
        "itemId": "pegasus",
        "baseChance": 0.16666666666666666
      },
      {
        "itemId": "guest666",
        "baseChance": 0.16666666666666666
      },
      {
        "itemId": "foxini",
        "baseChance": 0.16666666666666666
      }
    ]
  },
  {
    "id": "dragon",
    "name": "Dragon",
    "price": 499,
    "subtitle": "",
    "hue": 0,
    "tag": "",
    "image": "img/cases/dragon.png",
    "drops": [
      {
        "itemId": "burguro",
        "baseChance": 0.16666666666666666
      },
      {
        "itemId": "pegasus",
        "baseChance": 0.16666666666666666
      },
      {
        "itemId": "cookie",
        "baseChance": 0.16666666666666666
      },
      {
        "itemId": "fortunu",
        "baseChance": 0.16666666666666666
      },
      {
        "itemId": "venuspino",
        "baseChance": 0.16666666666666666
      },
      {
        "itemId": "dragon",
        "baseChance": 0.16666666666666666
      }
    ]
  }
]);
export const CASE_BY_ID = Object.fromEntries(CASES.map(c => [c.id, c]));
