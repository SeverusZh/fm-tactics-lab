'use strict';
// Translate presentation nodes only. Native IDs, control values, JSON, paths,
// imported names, saved scenarios and logs retain their original bytes.
window.FM27I18n = (() => {
 const dictionary = window.FM27English || {};
 const phrases = new RegExp(Object.keys(dictionary).sort((a,b)=>b.length-a.length).join('|'), 'g');
 const normalize = language => /^zh(?:[-_]|$)/i.test(language || '') ? 'zh-CN' : 'en';
 let language = normalize(navigator.language), observer;
 const ignored = 'script,style,pre,code,textarea,[contenteditable],[translate="no"],[data-i18n-skip]';
 const names = new Set();
 let seen = new WeakSet();
 function remember(value) {
  if (!value || typeof value !== 'object' || seen.has(value)) return;
  seen.add(value);
  if (Array.isArray(value)) { for (const row of value) remember(row); return; }
  for (const [key, item] of Object.entries(value)) {
   if (['name','tactic_name','club_name','filename','source','path','directory'].includes(key) && typeof item === 'string' && /[\u3400-\u9fff]/.test(item) && !/^(主队|客队)(球员 \d+)?$/.test(item)) names.add(item);
   else if (item && typeof item === 'object' && !['attributes','phases','instructions','native_source_plan','role_eligibility_context','pi_policies'].includes(key)) remember(item);
  }
 }
 function refreshNames() {
  names.clear();seen=new WeakSet();
  // Each optional page is loaded after this module, so guard lexical bindings.
  for (const read of [()=>state,()=>reference,()=>saveInfo,()=>saveRoster,()=>saveOpponents,()=>saveLoaded,()=>librarySave,()=>libraryReport,()=>selectedJob?.runs?.[selectedJob?.detailIndex || 0]]) {
   try { remember(read()); } catch (_) { /* Page is not initialized yet. */ }
  }
 }
 function translate(source, protectedNames = names) {
  if (language !== 'en' || !/[\u3400-\u9fff]/.test(source)) return source;
  const held = [];
  let text = source;
  for (const name of [...protectedNames].sort((a,b)=>b.length-a.length)) {
   if (text.includes(name)) {
    const token = `\uE000${held.length}\uE001`;
    text = text.split(name).join(token); held.push(name);
   }
  }
  text = text.replace(/[\u3400-\u9fff]+/g, word => dictionary[word] === undefined ? word.replace(phrases, phrase=>` ${dictionary[phrase]} `) : ` ${dictionary[word]} `)
   .replace(/（/g,' (' ).replace(/）/g,')').replace(/：/g,': ').replace(/；/g,'; ').replace(/。/g,'. ').replace(/、/g,', ').replace(/，/g,', ')
   .replace(/ {2,}/g,' ').trim()
   .replace(/\uE000(\d+)\uE001/g, (_, index) => held[Number(index)]);
  return (source.match(/^\s*/)[0])+text+(source.match(/\s*$/)[0]);
 }
 function project(root) {
  if (language !== 'en') return;
  if (root.nodeType === 3) {
   if (!root.parentElement?.closest(ignored)) { const text=translate(root.data); if(text!==root.data)root.data=text; }
   return;
  }
  if (root.nodeType !== 1 || root.matches(ignored)) return;
  for (const attr of ['title','placeholder','aria-label']) {
   if(root.hasAttribute(attr)){const original=root.getAttribute(attr),translated=translate(original);if(original!==translated)root.setAttribute(attr,translated);}
  }
  for (const child of root.childNodes) project(child);
 }
 function flush(records) {
  refreshNames();
  observer.disconnect();
  for(const record of records){
   if(record.type==='childList') for(const node of record.addedNodes)project(node);
   else project(record.target);
  }
  observer.observe(document.documentElement,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:['title','placeholder','aria-label']});
 }
 const ready = fetch('/api/locale').then(response=>{if(!response.ok)throw Error('locale');return response.json();})
  .then(result=>{language=normalize(result.language);}).catch(()=>{}).then(()=>{
   document.documentElement.lang=language;
   if(language==='en'){
    refreshNames();project(document.documentElement);
    observer=new MutationObserver(flush);
    observer.observe(document.documentElement,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:['title','placeholder','aria-label']});
   }
  });
 return {ready,normalize,translate,get language(){return language;}};
})();
