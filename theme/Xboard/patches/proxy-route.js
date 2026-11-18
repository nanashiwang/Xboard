{default:{name:"residential-proxy",path:"/",component:cs.component,redirect:"/proxies",meta:{isHidden:false},children:[{
  name:"ResidentialProxies",path:"proxies",
  component:()=>Promise.resolve({
    name:"ResidentialProxyPanel",
    data:()=>({proxyActive:false,proxyGeneration:0,proxyCleanup:null,proxyError:false}),
    render(){return li("div",{class:"residential-panel"},[
      this.proxyError ? li("div",{class:"residential-panel-error",role:"alert"},[
        "家宽代理暂时未能加载，请重试。",li("button",{onClick:()=>{this.stopProxy();this.startProxy()}},"重新加载")
      ]) : null,
      li("div",{ref:"proxyContent"})
    ])},
    methods:{
      async startProxy(){
        if(this.proxyActive)return;
        this.proxyActive=true;this.proxyError=false;
        const generation=++this.proxyGeneration;
        try{
          if(!window.CapybaraResidentialProxies||window.__capybaraProxyLoading){
            if(!window.__capybaraProxyLoading){
              window.__capybaraProxyLoading=new Promise((resolve,reject)=>{
                const style=document.createElement("link");style.rel="stylesheet";style.href="__PROXY_CSS__";
                const script=document.createElement("script");script.src="__PROXY_JS__";
                let styleReady=false,scriptReady=false;
                const finish=()=>{if(styleReady&&scriptReady){clearTimeout(timer);resolve()}};
                const fail=()=>{clearTimeout(timer);style.remove();script.remove();window.CapybaraResidentialProxies=undefined;reject(new Error("proxy_assets_failed"))};
                const timer=setTimeout(fail,20000);
                style.onload=()=>{styleReady=true;finish()};style.onerror=fail;
                script.onload=()=>{scriptReady=true;finish()};script.onerror=fail;
                document.head.append(style,script);
              }).catch(error=>{window.__capybaraProxyLoading=null;throw error});
            }
            await window.__capybaraProxyLoading;
          }
          if(this.proxyActive&&generation===this.proxyGeneration){
            this.proxyCleanup=window.CapybaraResidentialProxies.mount(this.$refs.proxyContent,{
              onLogin:()=>{pd();this.$router.replace({path:"/login",query:{redirect:"/proxies"}})}
            });
          }
        }catch(error){if(this.proxyActive&&generation===this.proxyGeneration)this.proxyError=true}
      },
      stopProxy(){this.proxyActive=false;++this.proxyGeneration;this.proxyCleanup?.();this.proxyCleanup=null}
    },
    mounted(){this.startProxy()},activated(){this.startProxy()},
    deactivated(){this.stopProxy()},beforeUnmount(){this.stopProxy()}
  }),
  meta:{title:"家宽代理",icon:"mdi:ip-network-outline",order:11,group:{key:"subscribe",label:"订阅"}}
}]}}
