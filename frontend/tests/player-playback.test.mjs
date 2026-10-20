import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { test } from 'node:test';
import { parse, compileScript } from '@vue/compiler-sfc';
import ts from 'typescript';
import { createRenderer, nextTick } from 'vue';
import { createPinia, setActivePinia } from 'pinia';
const inline=code=>`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`;
const vue=import.meta.resolve('vue');
function moduleUrl(source,imports){
 let code=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
 for(const [name,url] of Object.entries(imports)) code=code.replaceAll(`'${name}'`,JSON.stringify(url)).replaceAll(`"${name}"`,JSON.stringify(url));
 return inline(code);
}
const apiUrl=inline('export const api={};');
const {api}=await import(apiUrl);
const storeUrl=moduleUrl(await readFile(new URL('../src/stores/player.ts',import.meta.url),'utf8'),{
 vue,pinia:import.meta.resolve('pinia'),'@/api/client':apiUrl,
 '@/utils/episodes':inline('export const episodeKey=e=>JSON.stringify([e.number,e.version,e.playerUrl]);'),
});
const {usePlayerStore}=await import(storeUrl);
const {descriptor}=parse(await readFile(new URL('../src/components/VideoPlayerModal.vue',import.meta.url),'utf8'));
const component=(await import(moduleUrl(compileScript(descriptor,{id:'playback-regression',inlineTemplate:true}).content,{
 vue,'@/stores/player':storeUrl,
 '@/utils/locale':inline('export const tx=v=>String(v??"");'),
 '@/stores/library':inline('export const useLibraryStore=()=>({markWatched(){}});'),
 'hls.js':inline('export default class Hls {static isSupported(){return false;}}'),
}))).default;
function mountPlayer(){
 const videos=[];
 const node=(type,text='')=>({type,text,children:[],parent:null,props:{}});
 const renderer=createRenderer({
  createElement(type){
   const el=node(type);
   if(type==='video'){
    Object.assign(el,{textTracks:[],src:'',plays:0,pauses:0,loads:0,error:null,
     play(){this.plays++;return Promise.resolve();},pause(){this.pauses++;},load(){this.loads++;},
     removeAttribute(name){if(name==='src')this.src='';}});
    videos.push(el);
   }return el;
  },
  createText:text=>node('text',text),createComment:text=>node('comment',text),
  setText:(el,text)=>el.text=text,setElementText:(el,text)=>el.text=text,
  parentNode:el=>el.parent,nextSibling:el=>el.parent?.children[el.parent.children.indexOf(el)+1]||null,
  patchProp:(el,key,old,value)=>el.props[key]=value,
  insert(el,parent,anchor=null){
   if(el.parent){const i=el.parent.children.indexOf(el);if(i>=0)el.parent.children.splice(i,1);}
   el.parent=parent;const i=anchor?parent.children.indexOf(anchor):-1;
   parent.children.splice(i<0?parent.children.length:i,0,el);
  },
  remove(el){if(el.parent){const i=el.parent.children.indexOf(el);if(i>=0)el.parent.children.splice(i,1);}el.parent=null;},
 });
 const root=node('root'),app=renderer.createApp(component);app.mount(root);
 return {videos,app,root};
}
test('local video loads on opening, stops on close, reloads the same file, and exposes media errors',async t=>{
 globalThis.window={addEventListener(){},removeEventListener(){}};
 setActivePinia(createPinia());api.getLocalSubtitles=async()=>[];
 const player=usePlayerStore();const {videos,app,root}=mountPlayer();
 t.after(()=>{app.unmount();delete globalThis.window;});
 await player.playLocalFile('task','Anime',160,'video.mp4');await nextTick();
 assert.equal(videos.length,1);assert.equal(videos[0].src,'/api/media/stream/task');
 assert.ok(videos[0].plays>0,'the video ref must exist before loading the URL');
 player.closePlayer();await nextTick();
 assert.equal(videos[0].src,'');assert.ok(videos[0].pauses>0);
 await player.playLocalFile('task','Anime',160,'video.mp4');await nextTick();
 assert.equal(videos.length,2);assert.equal(videos[1].src,'/api/media/stream/task');
 videos[1].error={code:4};videos[1].props.onError();await nextTick();
 assert.match(player.error,/format vidéo/);
 const buttons=[];function walk(el){if(el.type==='button')buttons.push(el);for(const c of el.children)walk(c);}walk(root);
 const retry=buttons.find(b=>b.text==='Réessayer');assert.ok(retry);
 const loads=videos[1].loads;retry.props.onClick();await nextTick();
 assert.equal(player.error,null);assert.ok(videos[1].loads>loads);
});
test('subtitle tracks use the real file list and stale responses cannot replace a local video',async()=>{
 setActivePinia(createPinia());const player=usePlayerStore();let finishRemote,finishOld;
 api.resolveVideoStream=()=>new Promise(resolve=>finishRemote=resolve);
 const remote=player.openPlayer('Remote','remote','french-manga',{number:1,playerUrl:'https://example.org/1'});
 api.getLocalSubtitles=()=>new Promise(resolve=>finishOld=resolve);
 const old=player.playLocalFile('old','Old',1);
 api.getLocalSubtitles=async()=>[{src:'/api/media/subtitle/new/0',srclang:'fr',label:'French'}];
 await player.playLocalFile('new','New',2);
 finishOld([{src:'/api/media/subtitle/old/0'}]);await old;
 finishRemote({streamUrl:'https://example.org/remote.mp4'});await remote;
 assert.equal(player.videoUrl,'/api/media/stream/new');
 assert.equal(player.selectedSubtitle,'/api/media/subtitle/new/0');assert.equal(player.isDownloaded,true);
 player.closePlayer();api.getLocalSubtitles=async()=>{throw new Error('optional subtitles failed');};
 await player.playLocalFile('none','No captions',1);
 assert.equal(player.error,null);assert.deepEqual(player.subtitles,[]);assert.equal(player.videoUrl,'/api/media/stream/none');
});
