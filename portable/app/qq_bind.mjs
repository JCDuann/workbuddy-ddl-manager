import { createRequire } from 'node:module';
import {writeFile,readFile,mkdir} from 'node:fs/promises';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
const root=path.dirname(fileURLToPath(import.meta.url));
const require=createRequire(path.join(root,'runtime','package.json'));
const {startQrConnect}=await import(new URL('./runtime/node_modules/@tencent-connect/qqbot-connector/dist/esm/index.js',import.meta.url));
const qrcode=require('qrcode');
const deployment=JSON.parse(await readFile(path.join(root,'deployment.json'),'utf8'));
const config=JSON.parse(await readFile(path.join(root,'qq_push.json'),'utf8'));
const python=deployment.python;
const expectedAppId=String(config.app_id);
const qrPath=process.argv[2];
if(!qrPath)throw new Error('需要二维码图片的输出路径');
const controller=new AbortController();
const timer=setTimeout(()=>controller.abort(),5*60*1000);
await new Promise((resolve,reject)=>{
 startQrConnect({
  onQrDisplayed:async url=>{
   await mkdir(path.dirname(qrPath),{recursive:true});
   await qrcode.toFile(qrPath,url,{width:420,margin:3,errorCorrectionLevel:'M'});
   await writeFile(path.join(root,'data','qq-bind-status.json'),JSON.stringify({status:'awaiting_scan',qr_image:qrPath,expected_app_id:expectedAppId,updated_at:new Date().toISOString()}));
   process.stdout.write(JSON.stringify({status:'awaiting_scan',qr_image:qrPath,expected_app_id:expectedAppId})+'\n');
  },
  onSuccess:credentials=>{
   const child=spawn(python,[path.join(root,'qq_message.py'),'store'],{windowsHide:true,stdio:['pipe','pipe','pipe']});
   let output='';child.stdout.on('data',part=>output+=part);
   const selected=credentials.find(value=>String(value.appId)===expectedAppId);
   child.stdin.end(JSON.stringify(selected??credentials[0]));
   child.on('exit',async code=>{
    let result;try{result=JSON.parse(output);}catch{result={stored:false,error:'无法保存授权凭据'};}
    const state={status:code===0?'authorized':'authorization_failed',...result,updated_at:new Date().toISOString()};
    await writeFile(path.join(root,'data','qq-bind-status.json'),JSON.stringify(state));
    process.stdout.write(JSON.stringify(state)+'\n');
    code===0?resolve():reject(new Error(result.error??'授权保存失败'));
   });
  },
  onFailure:error=>reject(error),
  onQrExpired:()=>process.stdout.write(JSON.stringify({status:'qr_refreshing'})+'\n')
 },{displayQrCodeToConsole:false,source:'DDLManager',signal:controller.signal});
}).catch(async error=>{
 const state={status:'not_authorized',error:controller.signal.aborted?'二维码授权等待已结束':error.message,updated_at:new Date().toISOString()};
 await writeFile(path.join(root,'data','qq-bind-status.json'),JSON.stringify(state));
 process.stdout.write(JSON.stringify(state)+'\n');process.exitCode=1;
}).finally(()=>clearTimeout(timer));
