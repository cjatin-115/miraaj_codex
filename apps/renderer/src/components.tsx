import React, {CSSProperties, ReactNode} from "react";
import {Audio, Img, OffthreadVideo, interpolate, useCurrentFrame, useVideoConfig} from "remotion";
import type {RenderProps, Scene, WordTimestamp} from "./types";

const FONT = 'Inter, "Arial", sans-serif';
const BG = "#0b0d10";
const ACCENT = "#c4b5fd";
const WHITE = "#f3f4f6";

export const FullscreenTalkingHead = ({src, scene, volume,hasAudio}: {src:string;scene:Scene;volume:number;hasAudio:boolean}) => <>
  <OffthreadVideo src={src} trimBefore={secFrame(scene.source_start)} durationInFrames={secFrame(scene.duration)} muted style={videoStyle(scene,"cover")} />
  {hasAudio&&<Audio src={src} trimBefore={secFrame(scene.source_start)} durationInFrames={secFrame(scene.duration)} volume={audioVolume(scene,volume)} />}
</>;

export const PunchInTalkingHead = ({src,scene,volume,hasAudio}:{src:string;scene:Scene;volume:number;hasAudio:boolean}) => {
  const frame=useCurrentFrame(); const {fps}=useVideoConfig();
  const progress=interpolate(frame,[0,Math.max(1,scene.duration*fps)],[1,scene.crop.scale ?? 1.08],{extrapolateRight:"clamp"});
  return <>
    <OffthreadVideo src={src} trimBefore={secFrame(scene.source_start)} durationInFrames={secFrame(scene.duration)} muted style={{...videoStyle(scene,"cover"),transform:`scale(${progress})`}} />
    {hasAudio&&<Audio src={src} trimBefore={secFrame(scene.source_start)} durationInFrames={secFrame(scene.duration)} volume={audioVolume(scene,volume)} />}
  </>;
};

export const RoundedTalkingHead = ({src,scene,volume,hasAudio}:{src:string;scene:Scene;volume:number;hasAudio:boolean}) => <>
  <div style={{position:"absolute",inset:"9% 7%",overflow:"hidden",borderRadius:42,border:"1px solid rgba(255,255,255,.16)",boxShadow:"0 30px 100px #0009"}}>
    <OffthreadVideo src={src} trimBefore={secFrame(scene.source_start)} durationInFrames={secFrame(scene.duration)} muted style={{...videoStyle(scene,"cover"),width:"100%",height:"100%"}} />
  </div>
  {hasAudio&&<Audio src={src} trimBefore={secFrame(scene.source_start)} durationInFrames={secFrame(scene.duration)} volume={audioVolume(scene,volume)} />}
</>;

export const OverlayTalkingHead = ({src,scene,volume,hasAudio}:{src:string;scene:Scene;volume:number;hasAudio:boolean}) => <>
  <div style={{position:"absolute",inset:"7% 8% 21%",overflow:"hidden",borderRadius:34}}><OffthreadVideo src={src} trimBefore={secFrame(scene.source_start)} durationInFrames={secFrame(scene.duration)} muted style={{...videoStyle(scene,"cover"),width:"100%",height:"100%"}} /></div>
  {hasAudio&&<Audio src={src} trimBefore={secFrame(scene.source_start)} durationInFrames={secFrame(scene.duration)} volume={audioVolume(scene,volume)} />}
</>;

export const SplitTalkingHead = ({src,scene,volume,hasAudio}:{src:string;scene:Scene;volume:number;hasAudio:boolean}) => <>
  <div style={{position:"absolute",left:70,right:70,top:330,bottom:330,overflow:"hidden",borderRadius:36}}><OffthreadVideo src={src} trimBefore={secFrame(scene.source_start)} durationInFrames={secFrame(scene.duration)} muted style={{...videoStyle(scene,"cover"),width:"100%",height:"100%"}} /></div>
  {hasAudio&&<Audio src={src} trimBefore={secFrame(scene.source_start)} durationInFrames={secFrame(scene.duration)} volume={volume} />}
</>;

export const WordCaption = ({words,sourceStart,style,emphasis=[]}:{words:WordTimestamp[];sourceStart:number;style:Record<string,any>;emphasis?:string[]}) => {
  const frame=useCurrentFrame(); const {fps}=useVideoConfig();
  const active=words.findIndex(word=>sourceStart+frame/fps>=word.start && sourceStart+frame/fps<word.end);
  return <div style={{position:"absolute",left:style.safe_area?.horizontal??72,right:style.safe_area?.horizontal??72,bottom:style.safe_area?.bottom??260,display:"flex",justifyContent:"center",flexWrap:"wrap",gap:12,textAlign:"center",fontFamily:FONT,fontSize:style.captions?.font_size??64,fontWeight:800,lineHeight:1.08,textShadow:"0 5px 26px #000",padding:"12px 20px"}}>
    {words.map((item,index)=>{const hot=active===index||emphasis.some(term=>term.toLowerCase()===item.word.replace(/[.,!?]/g,"").toLowerCase());return <span key={`${item.start}-${index}`} style={{color:hot?style.captions?.highlight_color??ACCENT:WHITE,transform:hot?"translateY(-2px) scale(1.025)":"none",transition:"color 120ms ease, transform 120ms ease",display:"inline-block"}}>{item.word}</span>;})}
  </div>;
};

export const KeywordCaption = ({text,emphasis=[]}:{text:string;emphasis?:string[]}) => <div style={captionBase}>{text.split(/(\s+)/).map((part,i)=><span key={i} style={{color:emphasis.includes(part.trim())?ACCENT:WHITE}}>{part}</span>)}</div>;
export const BigStatement = ({text}:{text:string}) => <div style={{...centered,fontFamily:FONT,fontSize:92,fontWeight:850,lineHeight:1.02,letterSpacing:"-.055em",textAlign:"center",padding:100,color:WHITE}}>{text}</div>;
export const EditorialText = ({text}:{text:string}) => <div style={{...centered,fontFamily:FONT,fontSize:66,fontWeight:650,lineHeight:1.1,padding:"0 100px",textAlign:"left",color:WHITE}}><span style={{borderLeft:`10px solid ${ACCENT}`,paddingLeft:36}}>{text}</span></div>;
export const CTA = ({text}:{text:string}) => <div style={{...centered,fontFamily:FONT,fontSize:64,fontWeight:800,color:WHITE,textAlign:"center"}}><div style={{background:ACCENT,color:"#17131f",padding:"28px 48px",borderRadius:28,boxShadow:"0 24px 80px #0008"}}>{text}</div></div>;

export const Screenshot = ({src}:{src?:string}) => {if(!src)throw new Error("Screenshot scene references an asset that is not available to the render worker.");return <div style={{...centered,inset:"12% 6%",overflow:"hidden",borderRadius:28,background:"#181a20",border:"1px solid #ffffff30",boxShadow:"0 32px 100px #0009"}}><Img src={src} style={{width:"100%",height:"100%",objectFit:"contain"}}/></div>;};
export const BrowserWindow = ({data}:{data:Record<string,unknown>}) => <VisualPanel title={String(data.url??"PRODUCT PREVIEW")} body={String(data.label??data.title??"")}/>;
export const CodeBlock = ({data}:{data:Record<string,unknown>}) => <VisualPanel title="CODE" body={String(data.code??data.label??"const idea = 'clear';") } mono/>;
export const ComparisonCard = ({data}:{data:Record<string,unknown>}) => <div style={{...centered,display:"flex",gap:20,padding:90,fontFamily:FONT}}><Card title="OLD" body={String((data.left as any)?.label??"Before")} color="#343643"/><div style={{color:ACCENT,fontSize:52,fontWeight:800,alignSelf:"center"}}>VS</div><Card title="NEW" body={String((data.right as any)?.label??"After")} color="#514477"/></div>;
export const StatCard = ({data}:{data:Record<string,unknown>}) => <div style={{...centered,textAlign:"center",fontFamily:FONT}}><div style={{fontSize:192,fontWeight:850,letterSpacing:"-.07em",color:ACCENT,lineHeight:.95}}>{String(data.value??"73%")}</div><div style={{fontSize:44,fontWeight:600,color:WHITE,marginTop:28}}>{String(data.label??"")}</div></div>;
export const ProductCard = ({data}:{data:Record<string,unknown>}) => <VisualPanel title={String(data.name??"FEATURE")} body={String(data.description??data.label??"")}/>;
export const Graph = ({data}:{data:Record<string,unknown>}) => {const vals=(Array.isArray(data.values)?data.values:[24,42,36,68,73]).map(Number);const max=Math.max(1,...vals);return <svg viewBox="0 0 900 620" style={{position:"absolute",inset:"22% 8%",width:"84%",height:"56%",overflow:"visible"}}><rect width="900" height="620" rx="42" fill="#171a20"/><path d="M90 500 H830 M90 350 H830 M90 200 H830" stroke="#ffffff20" strokeWidth="2"/>{vals.map((v,i)=><g key={i}><rect x={130+i*145} y={520-(v/max)*380} width="86" height={(v/max)*380} rx="20" fill={i===vals.length-1?ACCENT:"#7561a5"}/><text x={173+i*145} y={550} textAnchor="middle" fill="#c9c8d1" fontSize="22">{(Array.isArray(data.labels)?data.labels[i]:`Q${i+1}`) as string}</text></g>)}</svg>;};
export const Diagram = ({data}:{data:Record<string,unknown>}) => <VisualPanel title="THE FLOW" body={String(data.label??"Input  →  Process  →  Result")}/>;
export const ImageScene = ({src}:{src?:string}) => {if(!src)throw new Error("Image scene references an asset that is not available to the render worker.");return <Img src={src} style={{position:"absolute",width:"100%",height:"100%",objectFit:"cover"}}/>;};
export const VideoScene = ({src,scene}:{src?:string;scene:Scene}) => {if(!src)throw new Error("Video b-roll references an asset that is not available to the render worker.");return <OffthreadVideo src={src} trimBefore={0} durationInFrames={Math.round(scene.duration*30)} muted style={{position:"absolute",width:"100%",height:"100%",objectFit:"cover"}}/>;};
export const Quote = ({text}:{text:string}) => <div style={{...centered,padding:100,fontFamily:FONT,color:WHITE,fontSize:60,fontWeight:650,lineHeight:1.18,textAlign:"center"}}><span style={{color:ACCENT,fontSize:120,lineHeight:.5}}>“</span>{text}<div style={{fontSize:80,color:ACCENT}}>”</div></div>;

const VisualPanel = ({title,body,mono=false}:{title:string;body:string;mono?:boolean}) => <div style={{...centered,left:70,right:70,background:"linear-gradient(145deg,#20232b,#121419)",border:"1px solid #ffffff22",borderRadius:36,padding:54,color:WHITE,fontFamily:FONT,boxShadow:"0 36px 100px #0008"}}><div style={{color:ACCENT,fontSize:22,fontWeight:800,letterSpacing:".16em",marginBottom:30}}>{title}</div><div style={{fontSize:mono?34:50,fontWeight:650,lineHeight:1.2,whiteSpace:"pre-wrap",fontFamily:mono?"Consolas, monospace":FONT}}>{body}</div></div>;
const Card=({title,body,color}:{title:string;body:string;color:string})=><div style={{background:color,borderRadius:32,padding:42,minWidth:300,minHeight:400,display:"flex",flexDirection:"column",justifyContent:"space-between",color:WHITE}}><b style={{fontSize:25,letterSpacing:".12em"}}>{title}</b><span style={{fontSize:48,fontWeight:750,lineHeight:1.05}}>{body}</span></div>;

const captionBase:CSSProperties={position:"absolute",left:72,right:72,bottom:260,textAlign:"center",fontFamily:FONT,fontSize:64,fontWeight:800,color:WHITE,textShadow:"0 5px 26px #000"};
const centered:CSSProperties={position:"absolute",inset:0,display:"flex",alignItems:"center",justifyContent:"center"};
const secFrame=(seconds:number)=>Math.max(0,Math.round(seconds*30));
const videoStyle=(scene:Scene,fit:"cover"|"contain"):CSSProperties=>({position:"absolute",width:"100%",height:"100%",objectFit:fit,objectPosition:`${(scene.crop.focus_x??.5)*100}% ${(scene.crop.focus_y??.5)*100}%`,transform:`scale(${scene.crop.scale??1})`,background:BG});

const Effect=({children,type,duration,out=false}:{children:ReactNode;type:string;duration?:number;out?:boolean})=>{
  const frame=useCurrentFrame();const {fps,durationInFrames}=useVideoConfig();const frames=duration??durationInFrames;const transitionFrames=Math.max(1,Math.round(.3*fps));
  const p=out?interpolate(frame,[Math.max(0,frames-transitionFrames),frames],[1,0],{extrapolateLeft:"clamp",extrapolateRight:"clamp"}):interpolate(frame,[0,Math.min(transitionFrames,frames-1)],[0,1],{extrapolateRight:"clamp"});
  const opacity=type==="fade"?p:1;
  const transform=type==="zoom"?`scale(${out?1.08-.08*p:1.08-.08*p})`:type==="slide"?`translateY(${(1-p)*100}px)`:type==="whip"?`translateX(${(1-p)*650}px)`:type==="scale"?`scale(${.94+.06*p})`:type==="camera"?`scale(1.04) translateX(${Math.sin(frame/(fps*2))*12}px)`:"none";
  const filter=type==="blur"?`blur(${(1-p)*18}px)`:"none";
  const clipPath=type==="mask"?`inset(0 ${100-p*100}% 0 0 round 32px)`:undefined;
  return <div style={{position:"absolute",inset:0,opacity,transform,filter,clipPath,overflow:"hidden"}}>{children}</div>;
};
export const Fade=({children,duration,out}:{children:ReactNode;duration?:number;out?:boolean})=><Effect type="fade" duration={duration} out={out}>{children}</Effect>;
export const Zoom=({children,duration,out}:{children:ReactNode;duration?:number;out?:boolean})=><Effect type="zoom" duration={duration} out={out}>{children}</Effect>;
export const Slide=({children,duration,out}:{children:ReactNode;duration?:number;out?:boolean})=><Effect type="slide" duration={duration} out={out}>{children}</Effect>;
export const Blur=({children,duration,out}:{children:ReactNode;duration?:number;out?:boolean})=><Effect type="blur" duration={duration} out={out}>{children}</Effect>;
export const Scale=({children,duration,out}:{children:ReactNode;duration?:number;out?:boolean})=><Effect type="scale" duration={duration} out={out}>{children}</Effect>;
export const MaskReveal=({children,duration,out}:{children:ReactNode;duration?:number;out?:boolean})=><Effect type="mask" duration={duration} out={out}>{children}</Effect>;
export const CameraMove=({children,duration,out}:{children:ReactNode;duration?:number;out?:boolean})=><Effect type="camera" duration={duration} out={out}>{children}</Effect>;
export const Cut=({children}:{children:ReactNode})=><>{children}</>;
export const Whip=({children,duration,out}:{children:ReactNode;duration?:number;out?:boolean})=><Effect type="whip" duration={duration} out={out}>{children}</Effect>;

const typeComponent:Record<string,React.FC<any>>={talking_head:FullscreenTalkingHead,talking_head_zoom:PunchInTalkingHead,talking_head_overlay:OverlayTalkingHead,talking_head_split:SplitTalkingHead,talking_head_rounded:RoundedTalkingHead,fullscreen_text:BigStatement,keyword_text:KeywordCaption,editorial_text:EditorialText,cta:CTA,screenshot:Screenshot,browser:BrowserWindow,code:CodeBlock,comparison:ComparisonCard,statistics:StatCard,product_card:ProductCard,graph:Graph,diagram:Diagram,image_broll:ImageScene,video_broll:VideoScene,quote:Quote};

export const TimelineScene=({scene,props}:{scene:Scene;props:RenderProps})=>{
  const frame=useCurrentFrame();const {fps}=useVideoConfig();const total=Math.max(1,Math.round(scene.duration*fps));const transition=scene.transition_in??"cut";
  const type=scene.type;
  if(type.startsWith("talking_head")){const Component=type==="talking_head_overlay"&&scene.layout?.window==="rounded"?RoundedTalkingHead:typeComponent[type]??FullscreenTalkingHead;const content=<Component src={props.sourceUrl} scene={scene} volume={props.volume} hasAudio={Boolean(props.sourceHasAudio)}/>;return <SceneTransition scene={scene} duration={total}>{content}</SceneTransition>;}
  if(type==="caption"){
    const words=props.wordTimestamps.filter(word=>word.start>=scene.source_start-.01&&word.end<=scene.source_end+.06);
    return <SceneTransition scene={scene} duration={total}><WordCaption words={words.length?words:[{word:scene.text??"",start:scene.source_start,end:scene.source_end}]} sourceStart={scene.source_start} style={props.style} emphasis={scene.emphasis}/></SceneTransition>;
  }
  const Component=typeComponent[type]??EditorialText;const data=scene.asset_request?.data??{};
  const assetUrl=data.asset_id?props.assetUrls?.[String(data.asset_id)]:undefined;
  return <SceneTransition scene={scene} duration={total}><Component text={scene.text??String(data.label??"")} emphasis={scene.emphasis} data={data} src={assetUrl} scene={scene}/></SceneTransition>;
};

const SceneTransition=({scene,duration,children}:{scene:Scene;duration:number;children:ReactNode})=>{
  const type=scene.transition_in??"cut";const transitions:Record<string,React.ComponentType<any>>={fade:Fade,zoom:Zoom,slide:Slide,blur:Blur,scale:Scale,mask:MaskReveal,whip:Whip,cut:Cut};const Component=transitions[type]??Cut;
  const exitType=scene.transition_out??"cut";const Exit=transitions[exitType]??Cut;
  return <Component duration={duration}><Exit duration={duration} out>{children}</Exit></Component>;
};

const audioVolume=(scene:Scene,volume:number)=>(frame:number)=>{
  const sceneFrames=Math.max(1,Math.round(scene.duration*30));const fadeFrames=Math.min(6,Math.floor(sceneFrames/4));
  const fadeIn=fadeFrames?Math.min(1,frame/fadeFrames):1;const fadeOut=fadeFrames?Math.min(1,Math.max(0,(sceneFrames-frame)/fadeFrames)):1;
  return volume*Math.min(fadeIn,fadeOut);
};
