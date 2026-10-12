export async function connectServer() {
  let config;
  const localDemo=['localhost','127.0.0.1'].includes(location.hostname) && location.port==='5173';
  try {
    const response=await fetch('/runtime-config',{cache:'no-store'});
    if (!response.ok) return localDemo ? null : {locked:true,message:'Сервер приложения недоступен.'};
    config=await response.json();
    if (config.mode!=='server') return localDemo ? null : {locked:true,message:'Открой приложение через Telegram.'};
  } catch { return {locked:true,message:'Сервер недоступен. Попробуй открыть приложение позже.'}; }
  const telegram=window.Telegram?.WebApp;
  const client={config,locked:true,message:'Открой Brainrot Freebie через Telegram.'};
  if (!telegram?.initData) return client;
  try {
    let token='';
    async function request(path,body,key) {
      const response=await fetch(path,{method:body ? 'POST' : 'GET',headers:{'Content-Type':'application/json',...(token ? {Authorization:`Bearer ${token}`} : {}),...(key ? {'Idempotency-Key':key} : {})},...(body ? {body:JSON.stringify(body)} : {}),cache:'no-store'});
      const data=await response.json();
      if (!response.ok) { if(response.status===401 || response.status===403 && path==='/api/auth') client.locked=true; const error=new Error(typeof data.detail==='string' ? data.detail : 'Запрос отклонён'); error.retryable=response.status>=500; throw error; }
      return data;
    }
    token=(await request('/api/auth',{initData:telegram.initData})).token;
    client.catalog=await request('/api/catalog');
    client.state=await request('/api/state');
    client.offset=client.state.serverNow-Date.now();
    client.request=request;
    client.download=async path=>{
      const response=await fetch(path,{headers:{Authorization:`Bearer ${token}`},cache:'no-store'});
      if(!response.ok)throw new Error('Не удалось скачать резервную копию');
      return response.blob();
    };
    const retries=new Map();
    client.mutate=async(action,body)=>{
      const fingerprint=JSON.stringify([action,body]), key=retries.get(fingerprint) || crypto.randomUUID();
      try {const result=await request(`/api/action/${action}`,body,key);retries.delete(fingerprint);return result;}
      catch(error) {if(error.retryable || error instanceof TypeError)retries.set(fingerprint,key);else retries.delete(fingerprint);throw error;}
    };
    client.now=()=>Date.now()+client.offset;
    client.locked=false;
  } catch(error) {client.message=error.message;}
  return client;
}

export function sharedRocket(state) {
  const round=state.round;
  if (!round) return null;
  const stake=state.rocket?.roundId===round.id ? state.rocket : {status:'watching',stakeValue:0,autoCash:null,payout:0,cashAt:0};
  return {...stake,id:round.id,startAt:round.startAt,crash:round.ended ? round.crash : 100,capped:!!round.capped,ended:round.ended};
}

export async function verifyProof(proof,serverSeed) {
  const bytes=new TextEncoder(), hex=data=>[...new Uint8Array(data)].map(b=>b.toString(16).padStart(2,'0')).join('');
  const hash=hex(await crypto.subtle.digest('SHA-256',bytes.encode(serverSeed)));
  if(hash!==proof.serverHash) return {valid:false,detail:'Хеш server seed не совпадает'};
  const key=await crypto.subtle.importKey('raw',bytes.encode(serverSeed),{name:'HMAC',hash:'SHA-256'},false,['sign']);
  const draws=[];
  for(let cursor=0;cursor<40;cursor++) {const digest=hex(await crypto.subtle.sign('HMAC',key,bytes.encode(`${proof.clientSeed}:${proof.nonce}:${cursor}`)));draws.push(parseInt(digest.slice(0,13),16)/2**52);}
  return {valid:true,draws};
}
