// All economy, asset paths and case contents live here. BStars are demo coins.
export const SETTINGS = { rtp: 0.90, startingBalance: 500, topUp: 100, promo: 'MIAMI', promoReward: 100, storageKey: 'brainrot-freebie-v1' };
export const SLOT_RULES = { pairChance: 0.375, tripleChance: 0.03, pairMultiplier: 2, tripleMultiplier: 5 };
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
  {
    "id": "plant",
    "name": "Plant Party",
    "price": 50,
    "subtitle": "Маленький кейс. Большой вайб.",
    "hue": 0,
    "tag": "STARTER",
    "image": "img/cases/plant.png",
    "drops": [
      {
        "itemId": "bananito",
        "baseChance": 0.48
      },
      {
        "itemId": "foxini",
        "baseChance": 0.27
      },
      {
        "itemId": "burguro",
        "baseChance": 0.15
      },
      {
        "itemId": "capitano",
        "baseChance": 0.07
      },
      {
        "itemId": "venuspino",
        "baseChance": 0.025
      },
      {
        "itemId": "cerberus",
        "baseChance": 0.005
      }
    ],
    "theme": "Классика"
  },
  {
    "id": "ocean",
    "name": "Ocean Drive",
    "price": 100,
    "subtitle": "Поймай свою волну удачи.",
    "hue": 90,
    "tag": "FRESH",
    "image": "img/cases/plant.png",
    "drops": [
      {
        "itemId": "foxini",
        "baseChance": 0.48
      },
      {
        "itemId": "burguro",
        "baseChance": 0.27
      },
      {
        "itemId": "lavadorito",
        "baseChance": 0.15
      },
      {
        "itemId": "ketupatbro",
        "baseChance": 0.07
      },
      {
        "itemId": "dragon",
        "baseChance": 0.025
      },
      {
        "itemId": "garama",
        "baseChance": 0.005
      }
    ],
    "theme": "Классика"
  },
  {
    "id": "miami",
    "name": "Miami Vice",
    "price": 250,
    "subtitle": "Ночь, неон и редкие находки.",
    "hue": 200,
    "tag": "HOT",
    "image": "img/cases/plant.png",
    "drops": [
      {
        "itemId": "esok",
        "baseChance": 0.48
      },
      {
        "itemId": "capitano",
        "baseChance": 0.27
      },
      {
        "itemId": "venuspino",
        "baseChance": 0.15
      },
      {
        "itemId": "dragon",
        "baseChance": 0.07
      },
      {
        "itemId": "tictac",
        "baseChance": 0.025
      },
      {
        "itemId": "guest666",
        "baseChance": 0.005
      }
    ],
    "theme": "Классика"
  },
  {
    "id": "sunset",
    "name": "Golden Hour",
    "price": 500,
    "subtitle": "Для тех, кто целится выше.",
    "hue": 310,
    "tag": "PREMIUM",
    "image": "img/cases/plant.png",
    "drops": [
      {
        "itemId": "capitano",
        "baseChance": 0.48
      },
      {
        "itemId": "ketupatbro",
        "baseChance": 0.27
      },
      {
        "itemId": "dragon",
        "baseChance": 0.15
      },
      {
        "itemId": "fortunu",
        "baseChance": 0.07
      },
      {
        "itemId": "guest666",
        "baseChance": 0.025
      },
      {
        "itemId": "eviledon",
        "baseChance": 0.005
      }
    ],
    "theme": "Классика"
  },
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
        "baseChance": 0.33724637681159425
      },
      {
        "itemId": "bananito",
        "baseChance": 0.22
      },
      {
        "itemId": "esok",
        "baseChance": 0.16
      },
      {
        "itemId": "ketupat",
        "baseChance": 0.12
      },
      {
        "itemId": "tictac",
        "baseChance": 0.1
      },
      {
        "itemId": "garama",
        "baseChance": 0.06275362318840579
      }
    ],
    "theme": "Sahur"
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
        "baseChance": 0.45
      },
      {
        "itemId": "ketupat",
        "baseChance": 0.18
      },
      {
        "itemId": "garama",
        "baseChance": 0.14
      },
      {
        "itemId": "cash",
        "baseChance": 0.12
      },
      {
        "itemId": "pizza",
        "baseChance": 0.08
      },
      {
        "itemId": "burguro",
        "baseChance": 0.03
      }
    ],
    "theme": "Вкусный дроп"
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
        "baseChance": 0.55
      },
      {
        "itemId": "lavadorito",
        "baseChance": 0.23
      },
      {
        "itemId": "cash",
        "baseChance": 0.13
      },
      {
        "itemId": "cookie",
        "baseChance": 0.055
      },
      {
        "itemId": "fortunu",
        "baseChance": 0.025
      },
      {
        "itemId": "dragon",
        "baseChance": 0.01
      }
    ],
    "theme": "Деньги"
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
        "baseChance": 0.3
      },
      {
        "itemId": "capitano",
        "baseChance": 0.28
      },
      {
        "itemId": "cerberus",
        "baseChance": 0.17
      },
      {
        "itemId": "guest666",
        "baseChance": 0.12
      },
      {
        "itemId": "fortunu",
        "baseChance": 0.09
      },
      {
        "itemId": "foxini",
        "baseChance": 0.04
      }
    ],
    "theme": "Мифы"
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
        "itemId": "pegasus",
        "baseChance": 0.37145953757225436
      },
      {
        "itemId": "cookie",
        "baseChance": 0.3
      },
      {
        "itemId": "fortunu",
        "baseChance": 0.16
      },
      {
        "itemId": "ketupatbro",
        "baseChance": 0.07
      },
      {
        "itemId": "venuspino",
        "baseChance": 0.045
      },
      {
        "itemId": "dragon",
        "baseChance": 0.05354046242774568
      }
    ],
    "theme": "Мифы"
  },
  {
    "id": "night",
    "name": "Night Shift",
    "price": 59,
    "theme": "Ночная смена",
    "hue": 0,
    "image": "img/cases/night.png",
    "drops": [
      {
        "itemId": "esok",
        "baseChance": 0.38
      },
      {
        "itemId": "tictac",
        "baseChance": 0.3
      },
      {
        "itemId": "eviledon",
        "baseChance": 0.2
      },
      {
        "itemId": "guest666",
        "baseChance": 0.07
      },
      {
        "itemId": "cerberus",
        "baseChance": 0.04
      },
      {
        "itemId": "foxini",
        "baseChance": 0.01
      }
    ]
  },
  {
    "id": "feast",
    "name": "Пир",
    "price": 129,
    "theme": "Вкусный дроп",
    "hue": 0,
    "image": "img/cases/feast.png",
    "drops": [
      {
        "itemId": "ketupat",
        "baseChance": 0.55
      },
      {
        "itemId": "pizza",
        "baseChance": 0.22
      },
      {
        "itemId": "burguro",
        "baseChance": 0.13
      },
      {
        "itemId": "cookie",
        "baseChance": 0.06
      },
      {
        "itemId": "ketupatbro",
        "baseChance": 0.03
      },
      {
        "itemId": "dragon",
        "baseChance": 0.01
      }
    ]
  }
];
export const CASE_BY_ID = Object.fromEntries(CASES.map(c => [c.id, c]));
