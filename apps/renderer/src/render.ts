import {readFile, mkdir} from "node:fs/promises";
import path from "node:path";
import {fileURLToPath} from "node:url";
import {bundle} from "@remotion/bundler";
import {renderMedia, selectComposition} from "@remotion/renderer";
import type {RenderProps} from "./types";

type Request={input:string;output:string;profile?:"vertical_1080"|"vertical_4k"};
const here=path.dirname(fileURLToPath(import.meta.url));
const root=path.resolve(here,"..");
const emit=(event:Record<string,unknown>)=>process.stdout.write(`${JSON.stringify(event)}\n`);

async function run(){
  const request=JSON.parse(await readFile(process.argv[2],"utf8")) as Request;
  const props=JSON.parse(await readFile(request.input,"utf8")) as RenderProps;
  const profile=request.profile??"vertical_1080";
  const dimensions=profile==="vertical_4k"?{width:2160,height:3840}:{width:1080,height:1920};
  if(props.timeline.fps!==30)throw new Error("Miraaj render profile requires a 30 fps timeline.");
  if(props.timeline.width!==1080||props.timeline.height!==1920)throw new Error("Input timeline must remain in the canonical 1080x1920 logical profile.");
  props.outputWidth=dimensions.width;
  props.outputHeight=dimensions.height;
  await mkdir(path.dirname(request.output),{recursive:true});
  emit({event:"rendering",progress:0});
  const serveUrl=await bundle({entryPoint:path.join(here,"index.tsx"),publicDir:path.join(root,"public"),onProgress:p=>emit({event:"bundling",progress:Math.max(0,Math.min(1,p/100))})});
  const composition=await selectComposition({serveUrl,id:"MiraajTimeline",inputProps:props});
  await renderMedia({serveUrl,composition,inputProps:props,codec:"h264",crf:17,pixelFormat:"yuv420p",audioCodec:"aac",audioBitrate:"320k",outputLocation:request.output,concurrency:Math.max(1,Math.min(4,Number(process.env.MIRAAJ_RENDER_CONCURRENCY??2))),onProgress:({progress,renderedFrames,encodedFrames,stitchStage})=>{
    if(encodedFrames>0||stitchStage==="muxing")emit({event:"encoding",progress:Math.round(progress*100),renderedFrames,encodedFrames,stitchStage});
    else emit({event:"rendering",progress:Math.round(progress*100),renderedFrames,encodedFrames});
  }});
  emit({event:"completed",output:request.output});
}

run().catch(error=>{emit({event:"failed",error:error instanceof Error?error.message:String(error)});process.exitCode=1;});
