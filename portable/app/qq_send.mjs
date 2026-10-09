const {QQBot}=await import(new URL('./runtime/node_modules/@tencent-connect/qqbot-nodejs/dist/index.js',import.meta.url));
let input='';for await(const chunk of process.stdin)input+=chunk;
const options=JSON.parse(input);
const target={scope:'c2c',targetId:options.targetId};
let bot;
const send=async markdownSupport=>{
  bot=new QQBot({appId:options.appId,appSecret:options.appSecret,markdownSupport,userAgent:'DDLManager/1.0'});
  // No start()/WebSocket: inbound handling remains on the existing WorkBuddy connection.
  try{return await bot.sendText(target,markdownSupport?options.message:(options.plainMessage??options.message));}finally{bot.stop();}
};
try{
 let response,format='markdown';
 try{response=await send(true);}catch(error){
  if(error.bizCode!==40034090)throw error;
  response=await send(false);format='text';
 }
 if(!response?.id)throw new Error('QQ未返回消息ID');
 process.stdout.write(JSON.stringify({success:true,message_id:String(response.id),timestamp:response.timestamp,format,proactive:true})+'\n');
}catch(error){
 process.stdout.write(JSON.stringify({success:false,error:`QQ发送失败：HTTP ${error.httpStatus??'未知'}，业务码 ${error.bizCode??'未知'}`,uncertain:error.httpStatus===0})+'\n');
 process.exitCode=1;
}
