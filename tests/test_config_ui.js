const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const html=fs.readFileSync(require('node:path').join(__dirname,'../web/index.html'),'utf8');
const source=html.slice(html.indexOf('async function saveRules()'),html.indexOf('// ═══════════ Xiaomi'));
let response={ok:false,msg:'設定已更新，請重新整理'},payload,toasts=[];
const context={cfg:{_config_revision:'old',intent_rules:[]},document:{getElementById(){return {}}},collectRulesFromUI(){return 2},toast(x){toasts.push(x)},showAlert(){},async fetch(url,options){payload=JSON.parse(options.body);return {json:async()=>response}}};
vm.createContext(context);vm.runInContext(source,context);
(async()=>{await context.saveRules();assert.equal(toasts.length,0);assert.equal(payload.section,'rules');assert.equal(payload.revision,'old');response={ok:true,revision:'new'};await context.saveRules();assert.equal(context.cfg._config_revision,'new');assert.equal(toasts.length,1);console.log('Configuration UI conflict/success tests passed.');})().catch(e=>{console.error(e);process.exit(1)});
