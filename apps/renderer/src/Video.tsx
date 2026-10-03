import React from "react";
import {AbsoluteFill, Composition, Sequence, staticFile, useVideoConfig} from "remotion";
import {TimelineScene} from "./components";
import type {RenderProps} from "./types";

export const MiraajVideo=({timeline,sourceUrl,sourceHasAudio,wordTimestamps,assetUrls={},volume,style}:RenderProps)=>{
  const {fps}=useVideoConfig();
  const props={timeline,sourceUrl:sourceUrl.startsWith("http")?sourceUrl:staticFile(sourceUrl.replace(/^\/+/,"")),sourceHasAudio,assetUrls:Object.fromEntries(Object.entries(assetUrls).map(([id,url])=>[id,url.startsWith("http")?url:staticFile(url.replace(/^\/+/,""))])),wordTimestamps,volume,style};
  const scale=(useVideoConfig().width/timeline.width);
  return <AbsoluteFill style={{background:"#0b0d10",overflow:"hidden"}}><div style={{position:"absolute",left:0,top:0,width:timeline.width,height:timeline.height,transform:`scale(${scale})`,transformOrigin:"top left",overflow:"hidden"}}>
    {timeline.scenes.map(scene=><Sequence key={scene.id} name={`${scene.type} · ${scene.id}`} from={Math.max(0,Math.round(scene.start*fps))} durationInFrames={Math.max(1,Math.round(scene.duration*fps))} premountFor={Math.min(Math.round(.5*fps),Math.round(scene.duration*fps))}>
      <TimelineScene scene={scene} props={props}/>
    </Sequence>)}</div></AbsoluteFill>;
};

export const Root=()=> <>
  <Composition id="MiraajTimeline" component={MiraajVideo} width={1080} height={1920} fps={30} durationInFrames={30} defaultProps={{timeline:{version:1,width:1080,height:1920,fps:30,duration:1,style_id:"modern_creator_v1",scenes:[]},sourceUrl:"",sourceHasAudio:false,wordTimestamps:[],assetUrls:{},volume:1,style:{},outputWidth:1080,outputHeight:1920} as RenderProps} calculateMetadata={({props})=>({durationInFrames:Math.ceil(props.timeline.duration*props.timeline.fps),width:props.outputWidth??props.timeline.width,height:props.outputHeight??props.timeline.height,fps:props.timeline.fps})}/>
</>;
