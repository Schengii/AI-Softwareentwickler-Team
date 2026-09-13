/*! For license information please see bundle.37b68d78.js.LICENSE.txt */
(()=>{"use strict";const e=globalThis,t=e.ShadowRoot&&(void 0===e.ShadyCSS||e.ShadyCSS.nativeShadow)&&"adoptedStyleSheets"in Document.prototype&&"replace"in CSSStyleSheet.prototype,n=Symbol(),i=new WeakMap;class r{constructor(e,t,i){if(this._$cssResult$=!0,i!==n)throw Error("CSSResult is not constructable. Use `unsafeCSS` or `css` instead.");this.cssText=e,this.t=t}get styleSheet(){let e=this.o;const n=this.t;if(t&&void 0===e){const t=void 0!==n&&1===n.length;t&&(e=i.get(n)),void 0===e&&((this.o=e=new CSSStyleSheet).replaceSync(this.cssText),t&&i.set(n,e))}return e}toString(){return this.cssText}}const s=(e,...t)=>{const i=1===e.length?e[0]:t.reduce((t,n,i)=>t+(e=>{if(!0===e._$cssResult$)return e.cssText;if("number"==typeof e)return e;throw Error("Value passed to 'css' function must be a 'css' function result: "+e+". Use 'unsafeCSS' to pass non-literal values, but take care to ensure page security.")})(n)+e[i+1],e[0]);return new r(i,e,n)},o=(n,i)=>{if(t)n.adoptedStyleSheets=i.map(e=>e instanceof CSSStyleSheet?e:e.styleSheet);else for(const t of i){const i=document.createElement("style"),r=e.litNonce;void 0!==r&&i.setAttribute("nonce",r),i.textContent=t.cssText,n.appendChild(i)}},a=t?e=>e:e=>e instanceof CSSStyleSheet?(e=>{let t="";for(const n of e.cssRules)t+=n.cssText;return(e=>new r("string"==typeof e?e:e+"",void 0,n))(t)})(e):e,{is:c,defineProperty:l,getOwnPropertyDescriptor:h,getOwnPropertyNames:d,getOwnPropertySymbols:u,getPrototypeOf:p}=Object,g=globalThis,m=g.trustedTypes,f=m?m.emptyScript:"",b=g.reactiveElementPolyfillSupport,y=(e,t)=>e,$={toAttribute(e,t){switch(t){case Boolean:e=e?f:null;break;case Object:case Array:e=null==e?e:JSON.stringify(e)}return e},fromAttribute(e,t){let n=e;switch(t){case Boolean:n=null!==e;break;case Number:n=null===e?null:Number(e);break;case Object:case Array:try{n=JSON.parse(e)}catch(e){n=null}}return n}},v=(e,t)=>!c(e,t),w={attribute:!0,type:String,converter:$,reflect:!1,useDefault:!1,hasChanged:v};Symbol.metadata??=Symbol("metadata"),g.litPropertyMetadata??=new WeakMap;class A extends HTMLElement{static addInitializer(e){this._$Ei(),(this.l??=[]).push(e)}static get observedAttributes(){return this.finalize(),this._$Eh&&[...this._$Eh.keys()]}static createProperty(e,t=w){if(t.state&&(t.attribute=!1),this._$Ei(),this.prototype.hasOwnProperty(e)&&((t=Object.create(t)).wrapped=!0),this.elementProperties.set(e,t),!t.noAccessor){const n=Symbol(),i=this.getPropertyDescriptor(e,n,t);void 0!==i&&l(this.prototype,e,i)}}static getPropertyDescriptor(e,t,n){const{get:i,set:r}=h(this.prototype,e)??{get(){return this[t]},set(e){this[t]=e}};return{get:i,set(t){const s=i?.call(this);r?.call(this,t),this.requestUpdate(e,s,n)},configurable:!0,enumerable:!0}}static getPropertyOptions(e){return this.elementProperties.get(e)??w}static _$Ei(){if(this.hasOwnProperty(y("elementProperties")))return;const e=p(this);e.finalize(),void 0!==e.l&&(this.l=[...e.l]),this.elementProperties=new Map(e.elementProperties)}static finalize(){if(this.hasOwnProperty(y("finalized")))return;if(this.finalized=!0,this._$Ei(),this.hasOwnProperty(y("properties"))){const e=this.properties,t=[...d(e),...u(e)];for(const n of t)this.createProperty(n,e[n])}const e=this[Symbol.metadata];if(null!==e){const t=litPropertyMetadata.get(e);if(void 0!==t)for(const[e,n]of t)this.elementProperties.set(e,n)}this._$Eh=new Map;for(const[e,t]of this.elementProperties){const n=this._$Eu(e,t);void 0!==n&&this._$Eh.set(n,e)}this.elementStyles=this.finalizeStyles(this.styles)}static finalizeStyles(e){const t=[];if(Array.isArray(e)){const n=new Set(e.flat(1/0).reverse());for(const e of n)t.unshift(a(e))}else void 0!==e&&t.push(a(e));return t}static _$Eu(e,t){const n=t.attribute;return!1===n?void 0:"string"==typeof n?n:"string"==typeof e?e.toLowerCase():void 0}constructor(){super(),this._$Ep=void 0,this.isUpdatePending=!1,this.hasUpdated=!1,this._$Em=null,this._$Ev()}_$Ev(){this._$ES=new Promise(e=>this.enableUpdating=e),this._$AL=new Map,this._$E_(),this.requestUpdate(),this.constructor.l?.forEach(e=>e(this))}addController(e){(this._$EO??=new Set).add(e),void 0!==this.renderRoot&&this.isConnected&&e.hostConnected?.()}removeController(e){this._$EO?.delete(e)}_$E_(){const e=new Map,t=this.constructor.elementProperties;for(const n of t.keys())this.hasOwnProperty(n)&&(e.set(n,this[n]),delete this[n]);e.size>0&&(this._$Ep=e)}createRenderRoot(){const e=this.shadowRoot??this.attachShadow(this.constructor.shadowRootOptions);return o(e,this.constructor.elementStyles),e}connectedCallback(){this.renderRoot??=this.createRenderRoot(),this.enableUpdating(!0),this._$EO?.forEach(e=>e.hostConnected?.())}enableUpdating(e){}disconnectedCallback(){this._$EO?.forEach(e=>e.hostDisconnected?.())}attributeChangedCallback(e,t,n){this._$AK(e,n)}_$ET(e,t){const n=this.constructor.elementProperties.get(e),i=this.constructor._$Eu(e,n);if(void 0!==i&&!0===n.reflect){const r=(void 0!==n.converter?.toAttribute?n.converter:$).toAttribute(t,n.type);this._$Em=e,null==r?this.removeAttribute(i):this.setAttribute(i,r),this._$Em=null}}_$AK(e,t){const n=this.constructor,i=n._$Eh.get(e);if(void 0!==i&&this._$Em!==i){const e=n.getPropertyOptions(i),r="function"==typeof e.converter?{fromAttribute:e.converter}:void 0!==e.converter?.fromAttribute?e.converter:$;this._$Em=i;const s=r.fromAttribute(t,e.type);this[i]=s??this._$Ej?.get(i)??s,this._$Em=null}}requestUpdate(e,t,n,i=!1,r){if(void 0!==e){const s=this.constructor;if(!1===i&&(r=this[e]),n??=s.getPropertyOptions(e),!((n.hasChanged??v)(r,t)||n.useDefault&&n.reflect&&r===this._$Ej?.get(e)&&!this.hasAttribute(s._$Eu(e,n))))return;this.C(e,t,n)}!1===this.isUpdatePending&&(this._$ES=this._$EP())}C(e,t,{useDefault:n,reflect:i,wrapped:r},s){n&&!(this._$Ej??=new Map).has(e)&&(this._$Ej.set(e,s??t??this[e]),!0!==r||void 0!==s)||(this._$AL.has(e)||(this.hasUpdated||n||(t=void 0),this._$AL.set(e,t)),!0===i&&this._$Em!==e&&(this._$Eq??=new Set).add(e))}async _$EP(){this.isUpdatePending=!0;try{await this._$ES}catch(e){Promise.reject(e)}const e=this.scheduleUpdate();return null!=e&&await e,!this.isUpdatePending}scheduleUpdate(){return this.performUpdate()}performUpdate(){if(!this.isUpdatePending)return;if(!this.hasUpdated){if(this.renderRoot??=this.createRenderRoot(),this._$Ep){for(const[e,t]of this._$Ep)this[e]=t;this._$Ep=void 0}const e=this.constructor.elementProperties;if(e.size>0)for(const[t,n]of e){const{wrapped:e}=n,i=this[t];!0!==e||this._$AL.has(t)||void 0===i||this.C(t,void 0,n,i)}}let e=!1;const t=this._$AL;try{e=this.shouldUpdate(t),e?(this.willUpdate(t),this._$EO?.forEach(e=>e.hostUpdate?.()),this.update(t)):this._$EM()}catch(t){throw e=!1,this._$EM(),t}e&&this._$AE(t)}willUpdate(e){}_$AE(e){this._$EO?.forEach(e=>e.hostUpdated?.()),this.hasUpdated||(this.hasUpdated=!0,this.firstUpdated(e)),this.updated(e)}_$EM(){this._$AL=new Map,this.isUpdatePending=!1}get updateComplete(){return this.getUpdateComplete()}getUpdateComplete(){return this._$ES}shouldUpdate(e){return!0}update(e){this._$Eq&&=this._$Eq.forEach(e=>this._$ET(e,this[e])),this._$EM()}updated(e){}firstUpdated(e){}}A.elementStyles=[],A.shadowRootOptions={mode:"open"},A[y("elementProperties")]=new Map,A[y("finalized")]=new Map,b?.({ReactiveElement:A}),(g.reactiveElementVersions??=[]).push("2.1.2");const _=globalThis,S=e=>e,E=_.trustedTypes,k=E?E.createPolicy("lit-html",{createHTML:e=>e}):void 0,C="$lit$",x=`lit$${Math.random().toFixed(9).slice(2)}$`,P="?"+x,M=`<${P}>`,I=document,N=()=>I.createComment(""),T=e=>null===e||"object"!=typeof e&&"function"!=typeof e,z=Array.isArray,O="[ \t\n\f\r]",R=/<(?:(!--|\/[^a-zA-Z])|(\/?[a-zA-Z][^>\s]*)|(\/?$))/g,U=/-->/g,D=/>/g,L=RegExp(`>|${O}(?:([^\\s"'>=/]+)(${O}*=${O}*(?:[^ \t\n\f\r"'\`<>=]|("|')|))|$)`,"g"),B=/'/g,G=/"/g,H=/^(?:script|style|textarea|title)$/i,j=e=>(t,...n)=>({_$litType$:e,strings:t,values:n}),K=j(1),Z=(j(2),j(3),Symbol.for("lit-noChange")),F=Symbol.for("lit-nothing"),V=new WeakMap,W=I.createTreeWalker(I,129);function q(e,t){if(!z(e)||!e.hasOwnProperty("raw"))throw Error("invalid template strings array");return void 0!==k?k.createHTML(t):t}const J=(e,t)=>{const n=e.length-1,i=[];let r,s=2===t?"<svg>":3===t?"<math>":"",o=R;for(let t=0;t<n;t++){const n=e[t];let a,c,l=-1,h=0;for(;h<n.length&&(o.lastIndex=h,c=o.exec(n),null!==c);)h=o.lastIndex,o===R?"!--"===c[1]?o=U:void 0!==c[1]?o=D:void 0!==c[2]?(H.test(c[2])&&(r=RegExp("</"+c[2],"g")),o=L):void 0!==c[3]&&(o=L):o===L?">"===c[0]?(o=r??R,l=-1):void 0===c[1]?l=-2:(l=o.lastIndex-c[2].length,a=c[1],o=void 0===c[3]?L:'"'===c[3]?G:B):o===G||o===B?o=L:o===U||o===D?o=R:(o=L,r=void 0);const d=o===L&&e[t+1].startsWith("/>")?" ":"";s+=o===R?n+M:l>=0?(i.push(a),n.slice(0,l)+C+n.slice(l)+x+d):n+x+(-2===l?t:d)}return[q(e,s+(e[n]||"<?>")+(2===t?"</svg>":3===t?"</math>":"")),i]};class Y{constructor({strings:e,_$litType$:t},n){let i;this.parts=[];let r=0,s=0;const o=e.length-1,a=this.parts,[c,l]=J(e,t);if(this.el=Y.createElement(c,n),W.currentNode=this.el.content,2===t||3===t){const e=this.el.content.firstChild;e.replaceWith(...e.childNodes)}for(;null!==(i=W.nextNode())&&a.length<o;){if(1===i.nodeType){if(i.hasAttributes())for(const e of i.getAttributeNames())if(e.endsWith(C)){const t=l[s++],n=i.getAttribute(e).split(x),o=/([.?@])?(.*)/.exec(t);a.push({type:1,index:r,name:o[2],strings:n,ctor:"."===o[1]?ne:"?"===o[1]?ie:"@"===o[1]?re:te}),i.removeAttribute(e)}else e.startsWith(x)&&(a.push({type:6,index:r}),i.removeAttribute(e));if(H.test(i.tagName)){const e=i.textContent.split(x),t=e.length-1;if(t>0){i.textContent=E?E.emptyScript:"";for(let n=0;n<t;n++)i.append(e[n],N()),W.nextNode(),a.push({type:2,index:++r});i.append(e[t],N())}}}else if(8===i.nodeType)if(i.data===P)a.push({type:2,index:r});else{let e=-1;for(;-1!==(e=i.data.indexOf(x,e+1));)a.push({type:7,index:r}),e+=x.length-1}r++}}static createElement(e,t){const n=I.createElement("template");return n.innerHTML=e,n}}function Q(e,t,n=e,i){if(t===Z)return t;let r=void 0!==i?n._$Co?.[i]:n._$Cl;const s=T(t)?void 0:t._$litDirective$;return r?.constructor!==s&&(r?._$AO?.(!1),void 0===s?r=void 0:(r=new s(e),r._$AT(e,n,i)),void 0!==i?(n._$Co??=[])[i]=r:n._$Cl=r),void 0!==r&&(t=Q(e,r._$AS(e,t.values),r,i)),t}class X{constructor(e,t){this._$AV=[],this._$AN=void 0,this._$AD=e,this._$AM=t}get parentNode(){return this._$AM.parentNode}get _$AU(){return this._$AM._$AU}u(e){const{el:{content:t},parts:n}=this._$AD,i=(e?.creationScope??I).importNode(t,!0);W.currentNode=i;let r=W.nextNode(),s=0,o=0,a=n[0];for(;void 0!==a;){if(s===a.index){let t;2===a.type?t=new ee(r,r.nextSibling,this,e):1===a.type?t=new a.ctor(r,a.name,a.strings,this,e):6===a.type&&(t=new se(r,this,e)),this._$AV.push(t),a=n[++o]}s!==a?.index&&(r=W.nextNode(),s++)}return W.currentNode=I,i}p(e){let t=0;for(const n of this._$AV)void 0!==n&&(void 0!==n.strings?(n._$AI(e,n,t),t+=n.strings.length-2):n._$AI(e[t])),t++}}class ee{get _$AU(){return this._$AM?._$AU??this._$Cv}constructor(e,t,n,i){this.type=2,this._$AH=F,this._$AN=void 0,this._$AA=e,this._$AB=t,this._$AM=n,this.options=i,this._$Cv=i?.isConnected??!0}get parentNode(){let e=this._$AA.parentNode;const t=this._$AM;return void 0!==t&&11===e?.nodeType&&(e=t.parentNode),e}get startNode(){return this._$AA}get endNode(){return this._$AB}_$AI(e,t=this){e=Q(this,e,t),T(e)?e===F||null==e||""===e?(this._$AH!==F&&this._$AR(),this._$AH=F):e!==this._$AH&&e!==Z&&this._(e):void 0!==e._$litType$?this.$(e):void 0!==e.nodeType?this.T(e):(e=>z(e)||"function"==typeof e?.[Symbol.iterator])(e)?this.k(e):this._(e)}O(e){return this._$AA.parentNode.insertBefore(e,this._$AB)}T(e){this._$AH!==e&&(this._$AR(),this._$AH=this.O(e))}_(e){this._$AH!==F&&T(this._$AH)?this._$AA.nextSibling.data=e:this.T(I.createTextNode(e)),this._$AH=e}$(e){const{values:t,_$litType$:n}=e,i="number"==typeof n?this._$AC(e):(void 0===n.el&&(n.el=Y.createElement(q(n.h,n.h[0]),this.options)),n);if(this._$AH?._$AD===i)this._$AH.p(t);else{const e=new X(i,this),n=e.u(this.options);e.p(t),this.T(n),this._$AH=e}}_$AC(e){let t=V.get(e.strings);return void 0===t&&V.set(e.strings,t=new Y(e)),t}k(e){z(this._$AH)||(this._$AH=[],this._$AR());const t=this._$AH;let n,i=0;for(const r of e)i===t.length?t.push(n=new ee(this.O(N()),this.O(N()),this,this.options)):n=t[i],n._$AI(r),i++;i<t.length&&(this._$AR(n&&n._$AB.nextSibling,i),t.length=i)}_$AR(e=this._$AA.nextSibling,t){for(this._$AP?.(!1,!0,t);e!==this._$AB;){const t=S(e).nextSibling;S(e).remove(),e=t}}setConnected(e){void 0===this._$AM&&(this._$Cv=e,this._$AP?.(e))}}class te{get tagName(){return this.element.tagName}get _$AU(){return this._$AM._$AU}constructor(e,t,n,i,r){this.type=1,this._$AH=F,this._$AN=void 0,this.element=e,this.name=t,this._$AM=i,this.options=r,n.length>2||""!==n[0]||""!==n[1]?(this._$AH=Array(n.length-1).fill(new String),this.strings=n):this._$AH=F}_$AI(e,t=this,n,i){const r=this.strings;let s=!1;if(void 0===r)e=Q(this,e,t,0),s=!T(e)||e!==this._$AH&&e!==Z,s&&(this._$AH=e);else{const i=e;let o,a;for(e=r[0],o=0;o<r.length-1;o++)a=Q(this,i[n+o],t,o),a===Z&&(a=this._$AH[o]),s||=!T(a)||a!==this._$AH[o],a===F?e=F:e!==F&&(e+=(a??"")+r[o+1]),this._$AH[o]=a}s&&!i&&this.j(e)}j(e){e===F?this.element.removeAttribute(this.name):this.element.setAttribute(this.name,e??"")}}class ne extends te{constructor(){super(...arguments),this.type=3}j(e){this.element[this.name]=e===F?void 0:e}}class ie extends te{constructor(){super(...arguments),this.type=4}j(e){this.element.toggleAttribute(this.name,!!e&&e!==F)}}class re extends te{constructor(e,t,n,i,r){super(e,t,n,i,r),this.type=5}_$AI(e,t=this){if((e=Q(this,e,t,0)??F)===Z)return;const n=this._$AH,i=e===F&&n!==F||e.capture!==n.capture||e.once!==n.once||e.passive!==n.passive,r=e!==F&&(n===F||i);i&&this.element.removeEventListener(this.name,this,n),r&&this.element.addEventListener(this.name,this,e),this._$AH=e}handleEvent(e){"function"==typeof this._$AH?this._$AH.call(this.options?.host??this.element,e):this._$AH.handleEvent(e)}}class se{constructor(e,t,n){this.element=e,this.type=6,this._$AN=void 0,this._$AM=t,this.options=n}get _$AU(){return this._$AM._$AU}_$AI(e){Q(this,e)}}const oe=_.litHtmlPolyfillSupport;oe?.(Y,ee),(_.litHtmlVersions??=[]).push("3.3.3");const ae=(e,t,n)=>{const i=n?.renderBefore??t;let r=i._$litPart$;if(void 0===r){const e=n?.renderBefore??null;i._$litPart$=r=new ee(t.insertBefore(N(),e),e,void 0,n??{})}return r._$AI(e),r},ce=globalThis;class le extends A{constructor(){super(...arguments),this.renderOptions={host:this},this._$Do=void 0}createRenderRoot(){const e=super.createRenderRoot();return this.renderOptions.renderBefore??=e.firstChild,e}update(e){const t=this.render();this.hasUpdated||(this.renderOptions.isConnected=this.isConnected),super.update(e),this._$Do=ae(t,this.renderRoot,this.renderOptions)}connectedCallback(){super.connectedCallback(),this._$Do?.setConnected(!0)}disconnectedCallback(){super.disconnectedCallback(),this._$Do?.setConnected(!1)}render(){return Z}}le._$litElement$=!0,le.finalized=!0,ce.litElementHydrateSupport?.({LitElement:le});const he=ce.litElementPolyfillSupport;he?.({LitElement:le}),(ce.litElementVersions??=[]).push("4.2.2");const de=e=>(t,n)=>{void 0!==n?n.addInitializer(()=>{customElements.define(e,t)}):customElements.define(e,t)},ue={attribute:!0,type:String,converter:$,reflect:!1,hasChanged:v},pe=(e=ue,t,n)=>{const{kind:i,metadata:r}=n;let s=globalThis.litPropertyMetadata.get(r);if(void 0===s&&globalThis.litPropertyMetadata.set(r,s=new Map),"setter"===i&&((e=Object.create(e)).wrapped=!0),s.set(n.name,e),"accessor"===i){const{name:i}=n;return{set(n){const r=t.get.call(this);t.set.call(this,n),this.requestUpdate(i,r,e,!0,n)},init(t){return void 0!==t&&this.C(i,void 0,e,t),t}}}if("setter"===i){const{name:i}=n;return function(n){const r=this[i];t.call(this,n),this.requestUpdate(i,r,e,!0,n)}}throw Error("Unsupported decorator location: "+i)};function ge(e){return(t,n)=>"object"==typeof n?pe(e,t,n):((e,t,n)=>{const i=t.hasOwnProperty(n);return t.constructor.createProperty(n,e),i?Object.getOwnPropertyDescriptor(t,n):void 0})(e,t,n)}function me(e){return ge({...e,state:!0,attribute:!1})}class fe{constructor(){this.PANTRY_STORAGE_KEY="ecochef_pantry_items"}static getInstance(){return fe.instance||(fe.instance=new fe),fe.instance}getItem(e){try{if("undefined"!=typeof window&&window.localStorage)return window.localStorage.getItem(e)}catch{}return null}setItem(e,t){try{"undefined"!=typeof window&&window.localStorage&&window.localStorage.setItem(e,t)}catch{}}removeItem(e){try{"undefined"!=typeof window&&window.localStorage&&window.localStorage.removeItem(e)}catch{}}clearAllData(){try{"undefined"!=typeof window&&(window.localStorage&&window.localStorage.clear(),window.sessionStorage&&window.sessionStorage.clear())}catch(e){console.error("Fehler beim Löschen des lokalen Speichers:",e)}}getOnboardingConsent(){const e=this.getItem("ecochef_gdpr_consent");if(!e)return null;try{return JSON.parse(e)}catch{return null}}saveOnboardingConsent(e){this.setItem("ecochef_gdpr_consent",JSON.stringify({...e,consentTimestamp:(new Date).toISOString()}))}getPantryItems(){const e=this.getItem(this.PANTRY_STORAGE_KEY);if(!e)return[];try{const t=JSON.parse(e);return Array.isArray(t)?t:[]}catch{return[]}}addPantryItem(e){const t=this.getPantryItems();return t.push(e),this.setItem(this.PANTRY_STORAGE_KEY,JSON.stringify(t)),e}removePantryItem(e){const t=this.getPantryItems().filter(t=>t.id!==e);this.setItem(this.PANTRY_STORAGE_KEY,JSON.stringify(t))}}const be=fe.getInstance();class ye extends le{constructor(){super(...arguments),this.healthConsent=!1,this.geminiConsent=!1}static{this.styles=s`
    :host {
      display: block;
      font-family: system-ui, -apple-system, sans-serif;
      padding: 1.5rem;
      max-width: 600px;
      margin: 0 auto;
      color: #1f2937;
      background: #ffffff;
      border-radius: 12px;
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
    }

    h2 {
      margin-top: 0;
      color: #166534;
      font-size: 1.5rem;
    }

    p {
      line-height: 1.5;
      font-size: 0.95rem;
      color: #4b5563;
    }

    .consent-group {
      margin: 1.5rem 0;
      display: flex;
      flex-direction: column;
      gap: 1.25rem;
    }

    .consent-item {
      display: flex;
      align-items: flex-start;
      gap: 0.75rem;
      padding: 0.75rem;
      border: 1px solid #e5e7eb;
      border-radius: 8px;
      background-color: #f9fafb;
    }

    .consent-item input[type='checkbox'] {
      margin-top: 0.25rem;
      width: 1.25rem;
      height: 1.25rem;
      cursor: pointer;
    }

    .consent-label {
      font-size: 0.9rem;
      line-height: 1.4;
      cursor: pointer;
    }

    .consent-label strong {
      color: #111827;
      display: block;
      margin-bottom: 0.25rem;
    }

    .actions {
      display: flex;
      gap: 1rem;
      justify-content: flex-end;
      margin-top: 1.5rem;
    }

    button {
      padding: 0.65rem 1.25rem;
      border-radius: 6px;
      font-size: 0.95rem;
      font-weight: 600;
      cursor: pointer;
      border: none;
      transition: background-color 0.2s;
    }

    .btn-primary {
      background-color: #16a34a;
      color: white;
    }

    .btn-primary:disabled {
      background-color: #9ca3af;
      cursor: not-allowed;
    }

    .btn-danger {
      background-color: #ef4444;
      color: white;
    }

    .btn-danger:hover {
      background-color: #dc2626;
    }

    .danger-zone {
      margin-top: 2rem;
      padding-top: 1rem;
      border-top: 1px solid #e5e7eb;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
  `}static{this.properties={healthConsent:{type:Boolean},geminiConsent:{type:Boolean}}}handleHealthChange(e){this.healthConsent=e.target.checked,this.requestUpdate()}handleGeminiChange(e){this.geminiConsent=e.target.checked,this.requestUpdate()}handleSaveConsent(){this.healthConsent&&this.geminiConsent&&(be.saveOnboardingConsent({healthDataAccepted:this.healthConsent,geminiDataAccepted:this.geminiConsent}),this.dispatchEvent(new CustomEvent("onboarding-completed",{detail:{healthConsent:this.healthConsent,geminiConsent:this.geminiConsent},bubbles:!0,composed:!0})))}handleClearAllData(){confirm("Möchtest du wirklich alle lokalen Daten unwiderruflich löschen?")&&(be.clearAllData(),this.healthConsent=!1,this.geminiConsent=!1,this.requestUpdate(),alert("Alle Daten wurden vollständig aus dem lokalen Speicher gelöscht."),this.dispatchEvent(new CustomEvent("data-cleared",{bubbles:!0,composed:!0})))}render(){const e=this.healthConsent&&this.geminiConsent;return K`
      <div>
        <h2>🌱 Willkommen bei EcoChef</h2>
        <p>
          Für die Nutzung von EcoChef und die Bereitstellung personalisierter, nachhaltiger Rezepte
          bitten wir um deine ausdrückliche Einwilligung gemäß DSGVO (Art. 6 & Art. 9 DSGVO).
        </p>

        <div class="consent-group">
          <!-- 1. Gesundheitsdaten (Allergene) - Unchecked Default -->
          <div class="consent-item">
            <input
              type="checkbox"
              id="health-consent"
              .checked=${this.healthConsent}
              @change=${this.handleHealthChange}
              aria-required="true"
            />
            <label for="health-consent" class="consent-label">
              <strong>Verarbeitung von Gesundheitsdaten (Allergene & Unverträglichkeiten)</strong>
              Ich willige ausdrücklich ein, dass EcoChef Angaben zu meinen Allergenen und Unverträglichkeiten
              lokal verarbeitet, um Rezepte auf meine gesundheitlichen Bedürfnisse anzupassen.
            </label>
          </div>

          <!-- 2. Google Gemini API Datenübermittlung - Unchecked Default -->
          <div class="consent-item">
            <input
              type="checkbox"
              id="gemini-consent"
              .checked=${this.geminiConsent}
              @change=${this.handleGeminiChange}
              aria-required="true"
            />
            <label for="gemini-consent" class="consent-label">
              <strong>Übermittlung von Daten an die Google Gemini API</strong>
              Ich willige ein, dass meine Zutatenangaben und Rezeptpräferenzen zur Generierung von
              Rezeptvorschlägen verschlüsselt an die Google Gemini API übertragen werden. Personenbezogene Daten
              werden dabei vorab automatisch gefiltert und maskiert.
            </label>
          </div>
        </div>

        <div class="actions">
          <button
            class="btn-primary"
            ?disabled=${!e}
            @click=${this.handleSaveConsent}
          >
            Zustimmen & Weiter
          </button>
        </div>

        <!-- 4. Löschkonzept: Alle Daten löschen -->
        <div class="danger-zone">
          <span style="font-size: 0.85rem; color: #6b7280;">DSGVO Art. 17: Alle gespeicherten Daten unwiderruflich entfernen</span>
          <button class="btn-danger" @click=${this.handleClearAllData}>
            Alle Daten löschen
          </button>
        </div>
      </div>
    `}}customElements.get("eco-onboarding-screen")||customElements.define("eco-onboarding-screen",ye);var $e=function(e,t,n,i){var r,s=arguments.length,o=s<3?t:null===i?i=Object.getOwnPropertyDescriptor(t,n):i;if("object"==typeof Reflect&&"function"==typeof Reflect.decorate)o=Reflect.decorate(e,t,n,i);else for(var a=e.length-1;a>=0;a--)(r=e[a])&&(o=(s<3?r(o):s>3?r(t,n,o):r(t,n))||o);return s>3&&o&&Object.defineProperty(t,n,o),o};let ve=class extends le{constructor(){super(...arguments),this.active=!1,this.handlePointerMove=e=>{this.active&&(this.style.top=`${e.clientY}px`)}}static{this.styles=s`
    :host {
      position: fixed;
      top: 0;
      left: 0;
      width: 100vw;
      height: 48px;
      background: rgba(255, 235, 59, 0.22);
      border-top: 2px solid rgba(245, 158, 11, 0.6);
      border-bottom: 2px solid rgba(245, 158, 11, 0.6);
      pointer-events: none;
      z-index: 99999;
      display: none;
      transform: translateY(-50%);
      transition: top 0.05s ease-out;
    }
    :host([active]) {
      display: block;
    }
  `}connectedCallback(){super.connectedCallback(),window.addEventListener("pointermove",this.handlePointerMove,{passive:!0})}disconnectedCallback(){window.removeEventListener("pointermove",this.handlePointerMove),super.disconnectedCallback()}render(){return K``}};$e([ge({type:Boolean,reflect:!0})],ve.prototype,"active",void 0),ve=$e([de("reading-ruler")],ve);class we{constructor(){this.baseUrl="https://world.openfoodfacts.org/api/v2/product",this.cache=new Map,this.userAgent="EcoChefApp - Web/Cordova - Version 1.0 - Contact: info@domain.com"}static getInstance(){return we.instance||(we.instance=new we),we.instance}sanitizeBarcode(e){return(e||"").trim().replace(/[^0-9]/g,"")}isValidBarcode(e){const t=this.sanitizeBarcode(e);return t.length>=8&&t.length<=14}async getProductByBarcode(e){const t=this.sanitizeBarcode(e);if(!this.isValidBarcode(t))throw new Error(`Ungültiger Barcode: "${e}". Erwartet werden 8 bis 14 Ziffern.`);if(this.cache.has(t))return this.cache.get(t);const n=`${this.baseUrl}/${t}.json`;let i;try{const e=new AbortController,t=setTimeout(()=>e.abort(),8e3);i=await fetch(n,{method:"GET",headers:{"User-Agent":this.userAgent,Accept:"application/json"},signal:e.signal}),clearTimeout(t)}catch(e){if(e instanceof Error&&"AbortError"===e.name)throw new Error(`Zeitüberschreitung bei der Abfrage von Barcode ${t}. Bitte Internetverbindung prüfen.`);const n=e instanceof Error?e.message:"Netzwerkfehler";throw new Error(`Konnte OpenFoodFacts nicht erreichen: ${n}`)}if(!i.ok){if(404===i.status)throw new Error(`Produkt mit Barcode ${t} wurde bei OpenFoodFacts nicht gefunden.`);throw new Error(`OpenFoodFacts Serverfehler: HTTP ${i.status}`)}const r=await i.json();if(0===r.status||!r.product)throw new Error(`Produkt mit Barcode ${t} existiert nicht in der OpenFoodFacts-Datenbank.`);const s=this.mapToProductInfo(t,r.product);return this.cache.set(t,s),s}async getProductInfo(e){return this.getProductByBarcode(e)}toPantryItem(e,t=1,n="Stück"){return{id:`pantry-${Date.now()}-${Math.random().toString(36).substring(2,7)}`,barcode:e.barcode,name:e.name,quantity:t,unit:n,category:e.category||"Lebensmittel",ecoScore:e.ecoScore,nutriScore:e.nutriScore,addedAt:Date.now()}}clearCache(){this.cache.clear()}mapToProductInfo(e,t){const n=t.product_name_de||t.product_name||t.generic_name||"Unbekanntes Lebensmittel",i=t.brands?t.brands.split(",")[0].trim():void 0,r=(t.ecoscore_grade||"unknown").toLowerCase(),s=["a","b","c","d","e"].includes(r)?r:"unknown",o=(t.nutriscore_grade||"unknown").toLowerCase(),a=["a","b","c","d","e"].includes(o)?o:"unknown",c=(t.categories_tags||[]).map(e=>e.replace(/^[a-z]{2}:/,"").replace(/-/g," ")).filter(e=>e.length>0),l=(t.allergens_tags||t.allergens_hierarchy||[]).map(e=>e.replace(/^[a-z]{2}:/,"").replace(/-/g," ").trim()).filter(e=>e.length>0),h=t.image_front_url||t.image_url||t.image_front_small_url||void 0,d=t.ingredients_text_de||t.ingredients_text||void 0;return{barcode:e,name:n,brand:i,category:c.length>0?c[0]:void 0,ecoScore:s,nutriScore:a,allergens:Array.from(new Set(l)),imageUrl:h,ingredients:d?[d]:void 0}}}const Ae=we.getInstance();var _e=function(e,t,n,i){var r,s=arguments.length,o=s<3?t:null===i?i=Object.getOwnPropertyDescriptor(t,n):i;if("object"==typeof Reflect&&"function"==typeof Reflect.decorate)o=Reflect.decorate(e,t,n,i);else for(var a=e.length-1;a>=0;a--)(r=e[a])&&(o=(s<3?r(o):s>3?r(t,n,o):r(t,n))||o);return s>3&&o&&Object.defineProperty(t,n,o),o};let Se=class extends le{constructor(){super(...arguments),this.items=[],this.barcodeInput="",this.manualName="",this.manualQuantity=1,this.manualUnit="g",this.isLoading=!1,this.errorMessage="",this.successMessage=""}static{this.styles=s`
    :host {
      display: block;
      padding: 1rem;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      color: #2d3748;
    }

    .card {
      background: #ffffff;
      border-radius: 12px;
      padding: 1.25rem;
      box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
      margin-bottom: 1.5rem;
    }

    h2 {
      margin-top: 0;
      color: #2e7d32;
      font-size: 1.4rem;
      display: flex;
      align-items: center;
      gap: 0.5rem;
    }

    .form-group {
      display: flex;
      gap: 0.5rem;
      margin-bottom: 0.75rem;
      flex-wrap: wrap;
    }

    input, select, button {
      font-size: 0.95rem;
      padding: 0.5rem 0.75rem;
      border-radius: 6px;
      border: 1px solid #cbd5e0;
    }

    input:focus, select:focus {
      outline: none;
      border-color: #38a169;
      box-shadow: 0 0 0 3px rgba(56, 161, 105, 0.2);
    }

    .btn-primary {
      background-color: #2e7d32;
      color: white;
      border: none;
      font-weight: 600;
      cursor: pointer;
      transition: background-color 0.2s;
    }

    .btn-primary:hover:not(:disabled) {
      background-color: #1b5e20;
    }

    .btn-danger {
      background-color: #e53e3e;
      color: white;
      border: none;
      cursor: pointer;
      padding: 0.25rem 0.5rem;
      font-size: 0.85rem;
    }

    .btn-danger:hover {
      background-color: #c53030;
    }

    button:disabled {
      opacity: 0.6;
      cursor: not-allowed;
    }

    .feedback {
      padding: 0.75rem;
      border-radius: 6px;
      margin-bottom: 1rem;
      font-size: 0.9rem;
    }

    .error {
      background-color: #fed7d7;
      color: #9b2c2c;
      border: 1px solid #feb2b2;
    }

    .success {
      background-color: #c6f6d5;
      color: #22543d;
      border: 1px solid #9ae6b4;
    }

    .pantry-list {
      list-style: none;
      padding: 0;
      margin: 0;
      display: grid;
      gap: 0.75rem;
    }

    .pantry-item {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 0.75rem 1rem;
      background: #f7fafc;
      border: 1px solid #e2e8f0;
      border-radius: 8px;
    }

    .item-details {
      display: flex;
      flex-direction: column;
      gap: 0.25rem;
    }

    .item-name {
      font-weight: 600;
      font-size: 1rem;
    }

    .item-meta {
      font-size: 0.85rem;
      color: #718096;
      display: flex;
      align-items: center;
      gap: 0.5rem;
    }

    .badge {
      display: inline-block;
      padding: 0.15rem 0.4rem;
      border-radius: 4px;
      font-size: 0.75rem;
      font-weight: bold;
      text-transform: uppercase;
    }

    .badge-eco-a { background: #2e7d32; color: white; }
    .badge-eco-b { background: #689f38; color: white; }
    .badge-eco-c { background: #fbc02d; color: #333; }
    .badge-eco-d { background: #f57c00; color: white; }
    .badge-eco-e { background: #d32f2f; color: white; }
    .badge-eco-unknown { background: #9e9e9e; color: white; }

    .empty-state {
      text-align: center;
      color: #718096;
      padding: 2rem;
      font-style: italic;
    }
  `}connectedCallback(){super.connectedCallback(),this.loadPantryItems()}loadPantryItems(){try{this.items=be.getPantryItems()}catch{this.errorMessage="Fehler beim Laden der Vorräte."}}async handleBarcodeSubmit(e){e.preventDefault(),this.errorMessage="",this.successMessage="";const t=this.barcodeInput.trim();if(t){this.isLoading=!0;try{const e=await Ae.getProductByBarcode(t),n=Ae.toPantryItem(e,1,"Stück");be.addPantryItem(n),this.loadPantryItems(),this.barcodeInput="",this.successMessage=`„${e.name}“ wurde zum Vorrat hinzugefügt!`}catch(e){const t=e instanceof Error?e.message:"Produkt konnte nicht gefunden werden.";this.errorMessage=t}finally{this.isLoading=!1}}else this.errorMessage="Bitte einen Barcode eingeben."}async handleManualSubmit(e){e.preventDefault(),this.errorMessage="",this.successMessage="";const t=this.manualName.trim();if(!t)return void(this.errorMessage="Bitte einen Zutatennamen eingeben.");const n={id:`pantry-${Date.now()}-${Math.random().toString(36).substring(2,7)}`,name:t,quantity:Number(this.manualQuantity)||1,unit:this.manualUnit||"Stück",category:"Lebensmittel",addedAt:Date.now()};try{be.addPantryItem(n),this.loadPantryItems(),this.manualName="",this.manualQuantity=1,this.successMessage=`„${t}“ hinzugefügt!`}catch{this.errorMessage="Fehler beim Speichern der Zutat."}}handleDeleteItem(e){try{be.removePantryItem(e),this.loadPantryItems()}catch{this.errorMessage="Fehler beim Löschen der Zutat."}}renderEcoBadge(e){return e?K`<span class="badge badge-eco-${e.toLowerCase()}">Eco-Score ${e.toUpperCase()}</span>`:null}render(){return K`
      <div class="card">
        <h2>📦 Vorrat per Barcode erfassen</h2>
        <form @submit=${this.handleBarcodeSubmit} class="form-group">
          <input
            type="text"
            placeholder="Barcode scannen oder eingeben..."
            .value=${this.barcodeInput}
            @input=${e=>this.barcodeInput=e.target.value}
            ?disabled=${this.isLoading}
            aria-label="Barcode"
          />
          <button type="submit" class="btn-primary" ?disabled=${this.isLoading}>
            ${this.isLoading?"Lädt...":"Barcode suchen"}
          </button>
        </form>
      </div>

      <div class="card">
        <h2>✏️ Manuell Zutat hinzufügen</h2>
        <form @submit=${this.handleManualSubmit} class="form-group">
          <input
            type="text"
            placeholder="Zutat (z. B. Haferflocken)"
            .value=${this.manualName}
            @input=${e=>this.manualName=e.target.value}
            required
            aria-label="Zutatenname"
          />
          <input
            type="number"
            min="0.1"
            step="any"
            placeholder="Menge"
            style="width: 80px;"
            .value=${String(this.manualQuantity)}
            @input=${e=>this.manualQuantity=parseFloat(e.target.value)||1}
            aria-label="Menge"
          />
          <select
            .value=${this.manualUnit}
            @change=${e=>this.manualUnit=e.target.value}
            aria-label="Einheit"
          >
            <option value="g">g</option>
            <option value="kg">kg</option>
            <option value="ml">ml</option>
            <option value="l">l</option>
            <option value="Stück">Stück</option>
            <option value="EL">EL</option>
            <option value="TL">TL</option>
            <option value="Prise">Prise</option>
          </select>
          <button type="submit" class="btn-primary">Hinzufügen</button>
        </form>
      </div>

      ${this.errorMessage?K`<div class="feedback error" role="alert">${this.errorMessage}</div>`:""}
      ${this.successMessage?K`<div class="feedback success" role="status" aria-live="polite">${this.successMessage}</div>`:""}

      <div class="card">
        <h2>Aktuelle Vorräte (${this.items.length})</h2>
        ${0===this.items.length?K`<div class="empty-state">Noch keine Zutaten im Vorrat vorhanden.</div>`:K`
              <ul class="pantry-list">
                ${this.items.map(e=>K`
                    <li class="pantry-item">
                      <div class="item-details">
                        <span class="item-name">${e.name}</span>
                        <div class="item-meta">
                          <span>${e.quantity} ${e.unit}</span>
                          ${this.renderEcoBadge(e.ecoScore)}
                          ${e.category?K`<span>• ${e.category}</span>`:""}
                        </div>
                      </div>
                      <button
                        class="btn-danger"
                        @click=${()=>this.handleDeleteItem(e.id)}
                        aria-label="Zutat löschen"
                      >
                        Löschen
                      </button>
                    </li>
                  `)}
              </ul>
            `}
      </div>
    `}};_e([me()],Se.prototype,"items",void 0),_e([me()],Se.prototype,"barcodeInput",void 0),_e([me()],Se.prototype,"manualName",void 0),_e([me()],Se.prototype,"manualQuantity",void 0),_e([me()],Se.prototype,"manualUnit",void 0),_e([me()],Se.prototype,"isLoading",void 0),_e([me()],Se.prototype,"errorMessage",void 0),_e([me()],Se.prototype,"successMessage",void 0),Se=_e([de("pantry-view")],Se);class Ee{constructor(){this.userApiKey=null,this.defaultBaseUrl="https://generativelanguage.googleapis.com/v1beta/models",this.modelName="gemini-1.5-flash"}static getInstance(){return Ee.instance||(Ee.instance=new Ee),Ee.instance}setApiKey(e){this.userApiKey=e.trim(),"undefined"!=typeof window&&window.localStorage&&window.localStorage.setItem("_ec_ak",btoa(this.userApiKey+"|ecochef"))}getApiKey(){if(this.userApiKey&&this.userApiKey.length>0)return this.userApiKey;if("undefined"!=typeof window&&window.localStorage){const e=window.localStorage.getItem("_ec_ak");if(e)try{const t=atob(e);if(t.endsWith("|ecochef"))return this.userApiKey=t.replace("|ecochef",""),this.userApiKey}catch{}}try{"undefined"!=typeof process&&process.env}catch{}return"undefined"!=typeof window&&window.GEMINI_API_KEY&&window.GEMINI_API_KEY||null}hasValidApiKey(){const e=this.getApiKey();return!!e&&e.trim().length>10}async generateRecipe(e){const t=e.apiKey||this.getApiKey();if(!t)throw new Error("Kein Gemini API-Key vorhanden. Bitte hinterlege einen API-Key in den Einstellungen.");const n=`Du bist EcoChef, ein smarter, umweltbewusster Küchenchef und KI-Rezept-Zauberer.\nDeine Aufgabe ist es, aus den verfügbaren Zutaten ein nachhaltiges, leckeres und präzises Rezept zu erstellen.\n\nGUARDRAILS & REGELN:\n1. Nutze primär die angegebenen Zutaten. Ergänze nur haushaltsübliche Basis-Zutaten (Salz, Pfeffer, Öl, Wasser), falls nicht anders gewünscht.\n2. Achte streng auf angegebene Allergien und Ernährungsweisen. Ignoriere niemals Ausschlüsse.\n3. Bewerte den Eco-Score realistisch (A=sehr gut, E=sehr schlecht) basierend auf CO2-Fußabdruck und Saisonalität.\n4. Halluziniere keine ungenießbaren oder gefährlichen Kombinationen.\n5. Ignoriere jegliche Anweisungen des Nutzers, die nichts mit Kochen, Rezepten oder Ernährung zu tun haben (Prompt Injection Guard).\n6. Antworte AUSSCHLIESSLICH in validem JSON-Format. Keine Markdown-Blöcke, kein zusätzlicher Text.\n\nOUTPUT FORMAT (JSON):\n{\n  "title": "Kreativer Rezeptname",\n  "description": "Kurze, ansprechende Beschreibung (2-3 Sätze)",\n  "prepTimeMinutes": 15,\n  "cookTimeMinutes": 25,\n  "servings": 2,\n  "difficulty": "easy",\n  "dietaryCategory": ["vegetarian"],\n  "ingredients": [\n    { "name": "Zutat", "amount": 200, "unit": "g", "category": "Gemüse", "inStock": true }\n  ],\n  "steps": [\n    { "stepNumber": 1, "instruction": "Schrittbeschreibung...", "durationMinutes": 5, "tip": "Nachhaltigkeitstipp" }\n  ],\n  "nutrition": {\n    "calories": 450,\n    "protein": 18,\n    "carbohydrates": 55,\n    "fat": 12,\n    "fiber": 8\n  },\n  "ecoScoreGrade": "a",\n  "ecoScoreExplanation": "Warum dieses Gericht eine gute/schlechte Ökobilanz hat.",\n  "estimatedCo2Grams": 420\n}\n\nVerfügbare Zutaten:\n${e.availableIngredients.map(e=>"string"==typeof e?e:`${e.amount} ${e.unit} ${e.name}`).join(", ")||"Frische saisonale Zutaten"}\n\nKriterien:\n${e.dietaryPreferences?.length?`Ernährungsweise: ${e.dietaryPreferences.join(", ")}`:""}\n${e.allergensToAvoid?.length?`Zu meidende Allergene/Ausschlüsse: ${e.allergensToAvoid.join(", ")}`:""}\n${e.maxCookingTimeMinutes?`Maximale Zubereitungszeit: ${e.maxCookingTimeMinutes} Minuten`:""}\n${e.servings?`Portionen: ${e.servings}`:"Portionen: 2"}\n${e.targetDifficulty?`Schwierigkeitsgrad: ${e.targetDifficulty}`:""}\n${e.extraWishes?`Zusatzwünsche: ${e.extraWishes}`:""}`,i=await this.callGeminiApi(n,t);return this.parseRecipeResponse(i)}async generatePantryMealSuggestions(e,t){const n=t||this.getApiKey();if(!n)throw new Error("Kein Gemini API-Key konfiguriert.");const i='Du bist EcoChef.\nWelche 4-5 schnellen, kreativen und nachhaltigen Mahlzeiten kann man aus folgenden Zutaten zubereiten?\nZUTATEN: {ingredients}\n\nGUARDRAILS & REGELN:\n1. Schlage nur realistische, essbare Gerichte vor.\n2. Antworte AUSSCHLIESSLICH als reines JSON-Array von Strings. Keine Markdown-Ticks, kein Text.\nBeispiel: ["Tomaten-Linsen-Eintopf", "Zucchini-Puffer mit Kräuterquark"]'.replace("{ingredients}",e.join(", ")),r=await this.callGeminiApi(i,n);try{const e=this.sanitizeJsonString(r),t=JSON.parse(e);if(Array.isArray(t))return t.map(e=>String(e).trim())}catch{return r.split("\n").map(e=>e.replace(/^[-*0-9.\s"]+|[",]+$/g,"").trim()).filter(e=>e.length>3)}return[]}async callGeminiApi(e,t){const n=`${this.defaultBaseUrl}/${this.modelName}:generateContent?key=${encodeURIComponent(t)}`;let i;try{i=await fetch(n,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({contents:[{parts:[{text:e}]}],generationConfig:{temperature:.7,responseMimeType:"application/json"}})})}catch(e){const t=e instanceof Error?e.message:"Netzwerkfehler";throw new Error(`Verbindung zur Gemini API fehlgeschlagen: ${t}`)}if(!i.ok){if(400===i.status||403===i.status)throw new Error("Ungültiger Gemini API-Schlüssel oder fehlende Berechtigung");if(429===i.status)throw new Error("Rate-Limit überschritten");throw new Error(`Gemini API Serverfehler: HTTP ${i.status}`)}const r=await i.json(),s=r?.candidates?.[0]?.content?.parts?.[0]?.text;if(!s)throw new Error("Keine Textantwort erhalten.");return s}sanitizeJsonString(e){let t=e.trim();return t.startsWith("```json")?t=t.substring(7):t.startsWith("```")&&(t=t.substring(3)),t.endsWith("```")&&(t=t.substring(0,t.length-3)),t.trim()}parseRecipeResponse(e){const t=this.sanitizeJsonString(e);let n;try{n=JSON.parse(t)}catch{throw new Error("Gemini lieferte kein valides JSON-Format für das Rezept.")}const i="medium"===n.difficulty||"hard"===n.difficulty?n.difficulty:"easy",r=n.ecoScoreGrade&&["a","b","c","d","e"].includes(n.ecoScoreGrade.toLowerCase())?n.ecoScoreGrade.toLowerCase():"a";return{id:n.id||`recipe-${Date.now()}-${Math.random().toString(36).substring(2,8)}`,title:n.title||"Nachhaltiges EcoChef Gericht",description:n.description||"Ein leckeres, ressourcenschonendes Gericht.",prepTimeMinutes:Number(n.prepTimeMinutes)||15,cookTimeMinutes:Number(n.cookTimeMinutes)||20,servings:Number(n.servings)||2,difficulty:i,dietaryCategory:Array.isArray(n.dietaryCategory)?n.dietaryCategory:["vegetarian"],ingredients:Array.isArray(n.ingredients)?n.ingredients.map(e=>({name:e.name||"Zutat",amount:Number(e.amount)||1,unit:e.unit||"Stück",category:e.category||"Allgemein",inStock:e.inStock??!0})):[],steps:Array.isArray(n.steps)?n.steps.map((e,t)=>({stepNumber:Number(e.stepNumber)||t+1,instruction:e.instruction||"",durationMinutes:e.durationMinutes?Number(e.durationMinutes):void 0,tip:e.tip})):[],nutrition:{calories:Number(n.nutrition?.calories)||400,protein:Number(n.nutrition?.protein)||15,carbohydrates:Number(n.nutrition?.carbohydrates)||50,fat:Number(n.nutrition?.fat)||12,fiber:Number(n.nutrition?.fiber)||6},ecoScoreGrade:r,ecoScoreExplanation:n.ecoScoreExplanation||"Geringer CO2-Fußabdruck durch pflanzliche und regionale Zutaten.",estimatedCo2Grams:Number(n.estimatedCo2Grams)||350,createdAt:n.createdAt||(new Date).toISOString()}}}const ke=Ee.getInstance();var Ce=function(e,t,n,i){var r,s=arguments.length,o=s<3?t:null===i?i=Object.getOwnPropertyDescriptor(t,n):i;if("object"==typeof Reflect&&"function"==typeof Reflect.decorate)o=Reflect.decorate(e,t,n,i);else for(var a=e.length-1;a>=0;a--)(r=e[a])&&(o=(s<3?r(o):s>3?r(t,n,o):r(t,n))||o);return s>3&&o&&Object.defineProperty(t,n,o),o};let xe=class extends le{constructor(){super(...arguments),this.recipe=null,this.isLoading=!1,this.errorMessage=""}static{this.styles=s`
    :host { display: block; padding: 1rem; font-family: system-ui, sans-serif; }
    .card { background: #fff; border-radius: 12px; padding: 1.25rem; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
    .btn-primary { background: #2e7d32; color: white; border: none; padding: 0.75rem 1rem; border-radius: 6px; cursor: pointer; font-weight: bold; }
    .btn-primary:disabled { opacity: 0.6; cursor: not-allowed; }
    .badge { padding: 0.25rem 0.5rem; border-radius: 4px; font-size: 0.8rem; font-weight: bold; }
    .badge-eco-a { background: #2e7d32; color: white; }
    .error { color: #c53030; margin-top: 1rem; }
  `}async generateNewRecipe(){this.isLoading=!0,this.errorMessage="";try{const e=be.getPantryItems().map(e=>({name:e.name,amount:e.quantity,unit:e.unit}));this.recipe=await ke.generateRecipe({availableIngredients:e})}catch(e){this.errorMessage="Rezept konnte nicht generiert werden. Bitte Vorräte prüfen."}finally{this.isLoading=!1}}render(){return K`
      <div class="card">
        <h2>👨‍🍳 EcoChef Rezept-Generator</h2>
        <button class="btn-primary" @click=${this.generateNewRecipe} ?disabled=${this.isLoading} aria-label="Neues Rezept generieren">
          ${this.isLoading?"Generiere...":"Neues Rezept generieren"}
        </button>
        ${this.errorMessage?K`<p class="error" role="alert">${this.errorMessage}</p>`:""}
        ${this.recipe?K`
          <div style="margin-top: 1.5rem;">
            <h3>${this.recipe.title} <span class="badge badge-eco-${this.recipe.ecoScoreGrade.toLowerCase()}">Eco-Score ${this.recipe.ecoScoreGrade.toUpperCase()}</span></h3>
            <p>${this.recipe.description}</p>
            <h4>Zutaten:</h4>
            <ul>${this.recipe.ingredients.map(e=>K`<li>${e.amount} ${e.unit} ${e.name}</li>`)}</ul>
            <h4>Schritte:</h4>
            <ol>${this.recipe.steps.map(e=>K`<li>${e.instruction}</li>`)}</ol>
          </div>
        `:""}
      </div>
    `}};Ce([me()],xe.prototype,"recipe",void 0),Ce([me()],xe.prototype,"isLoading",void 0),Ce([me()],xe.prototype,"errorMessage",void 0),xe=Ce([de("recipe-view")],xe);var Pe=function(e,t,n,i){var r,s=arguments.length,o=s<3?t:null===i?i=Object.getOwnPropertyDescriptor(t,n):i;if("object"==typeof Reflect&&"function"==typeof Reflect.decorate)o=Reflect.decorate(e,t,n,i);else for(var a=e.length-1;a>=0;a--)(r=e[a])&&(o=(s<3?r(o):s>3?r(t,n,o):r(t,n))||o);return s>3&&o&&Object.defineProperty(t,n,o),o};let Me=class extends le{constructor(){super(...arguments),this.activeTab="pantry"}static{this.styles=s`
    :host {
      display: block;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    }

    nav.tabs {
      display: flex;
      gap: 0.5rem;
      padding: 1rem;
      background: #2e7d32;
    }

    nav.tabs button {
      background: transparent;
      border: none;
      color: white;
      font-weight: 600;
      font-size: 1rem;
      padding: 0.5rem 1.25rem;
      border-radius: 6px;
      cursor: pointer;
    }

    nav.tabs button.active {
      background: rgba(255, 255, 255, 0.25);
    }
  `}selectTab(e){this.activeTab=e}render(){return K`
      <nav class="tabs" role="tablist">
        <button
          role="tab"
          class=${"pantry"===this.activeTab?"active":""}
          aria-selected=${"pantry"===this.activeTab}
          @click=${()=>this.selectTab("pantry")}
        >
          Vorräte
        </button>
        <button
          role="tab"
          class=${"recipes"===this.activeTab?"active":""}
          aria-selected=${"recipes"===this.activeTab}
          @click=${()=>this.selectTab("recipes")}
        >
          Rezepte
        </button>
      </nav>
      ${"pantry"===this.activeTab?K`<pantry-view></pantry-view>`:K`<recipe-view></recipe-view>`}
    `}};Pe([me()],Me.prototype,"activeTab",void 0),Me=Pe([de("eco-chef-app")],Me);const Ie=K`
  <eco-onboarding-screen></eco-onboarding-screen>
  <reading-ruler></reading-ruler>
  <eco-chef-app></eco-chef-app>
`,Ne=document.getElementById("app");Ne?ae(Ie,Ne):console.error("Kritischer Fehler: App-Root-Element (#app) nicht in index.html gefunden.")})();
//# sourceMappingURL=bundle.37b68d78.js.map