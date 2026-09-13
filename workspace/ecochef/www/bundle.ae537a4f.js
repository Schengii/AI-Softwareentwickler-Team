/*! For license information please see bundle.ae537a4f.js.LICENSE.txt */
(()=>{"use strict";const t=globalThis,e=t.ShadowRoot&&(void 0===t.ShadyCSS||t.ShadyCSS.nativeShadow)&&"adoptedStyleSheets"in Document.prototype&&"replace"in CSSStyleSheet.prototype,s=Symbol(),i=new WeakMap;class n{constructor(t,e,i){if(this._$cssResult$=!0,i!==s)throw Error("CSSResult is not constructable. Use `unsafeCSS` or `css` instead.");this.cssText=t,this.t=e}get styleSheet(){let t=this.o;const s=this.t;if(e&&void 0===t){const e=void 0!==s&&1===s.length;e&&(t=i.get(s)),void 0===t&&((this.o=t=new CSSStyleSheet).replaceSync(this.cssText),e&&i.set(s,t))}return t}toString(){return this.cssText}}const o=(t,...e)=>{const i=1===t.length?t[0]:e.reduce((e,s,i)=>e+(t=>{if(!0===t._$cssResult$)return t.cssText;if("number"==typeof t)return t;throw Error("Value passed to 'css' function must be a 'css' function result: "+t+". Use 'unsafeCSS' to pass non-literal values, but take care to ensure page security.")})(s)+t[i+1],t[0]);return new n(i,t,s)},r=(s,i)=>{if(e)s.adoptedStyleSheets=i.map(t=>t instanceof CSSStyleSheet?t:t.styleSheet);else for(const e of i){const i=document.createElement("style"),n=t.litNonce;void 0!==n&&i.setAttribute("nonce",n),i.textContent=e.cssText,s.appendChild(i)}},a=e?t=>t:t=>t instanceof CSSStyleSheet?(t=>{let e="";for(const s of t.cssRules)e+=s.cssText;return(t=>new n("string"==typeof t?t:t+"",void 0,s))(e)})(t):t,{is:h,defineProperty:l,getOwnPropertyDescriptor:c,getOwnPropertyNames:d,getOwnPropertySymbols:p,getPrototypeOf:u}=Object,g=globalThis,m=g.trustedTypes,f=m?m.emptyScript:"",$=g.reactiveElementPolyfillSupport,_=(t,e)=>t,b={toAttribute(t,e){switch(e){case Boolean:t=t?f:null;break;case Object:case Array:t=null==t?t:JSON.stringify(t)}return t},fromAttribute(t,e){let s=t;switch(e){case Boolean:s=null!==t;break;case Number:s=null===t?null:Number(t);break;case Object:case Array:try{s=JSON.parse(t)}catch(t){s=null}}return s}},y=(t,e)=>!h(t,e),v={attribute:!0,type:String,converter:b,reflect:!1,useDefault:!1,hasChanged:y};Symbol.metadata??=Symbol("metadata"),g.litPropertyMetadata??=new WeakMap;class A extends HTMLElement{static addInitializer(t){this._$Ei(),(this.l??=[]).push(t)}static get observedAttributes(){return this.finalize(),this._$Eh&&[...this._$Eh.keys()]}static createProperty(t,e=v){if(e.state&&(e.attribute=!1),this._$Ei(),this.prototype.hasOwnProperty(t)&&((e=Object.create(e)).wrapped=!0),this.elementProperties.set(t,e),!e.noAccessor){const s=Symbol(),i=this.getPropertyDescriptor(t,s,e);void 0!==i&&l(this.prototype,t,i)}}static getPropertyDescriptor(t,e,s){const{get:i,set:n}=c(this.prototype,t)??{get(){return this[e]},set(t){this[e]=t}};return{get:i,set(e){const o=i?.call(this);n?.call(this,e),this.requestUpdate(t,o,s)},configurable:!0,enumerable:!0}}static getPropertyOptions(t){return this.elementProperties.get(t)??v}static _$Ei(){if(this.hasOwnProperty(_("elementProperties")))return;const t=u(this);t.finalize(),void 0!==t.l&&(this.l=[...t.l]),this.elementProperties=new Map(t.elementProperties)}static finalize(){if(this.hasOwnProperty(_("finalized")))return;if(this.finalized=!0,this._$Ei(),this.hasOwnProperty(_("properties"))){const t=this.properties,e=[...d(t),...p(t)];for(const s of e)this.createProperty(s,t[s])}const t=this[Symbol.metadata];if(null!==t){const e=litPropertyMetadata.get(t);if(void 0!==e)for(const[t,s]of e)this.elementProperties.set(t,s)}this._$Eh=new Map;for(const[t,e]of this.elementProperties){const s=this._$Eu(t,e);void 0!==s&&this._$Eh.set(s,t)}this.elementStyles=this.finalizeStyles(this.styles)}static finalizeStyles(t){const e=[];if(Array.isArray(t)){const s=new Set(t.flat(1/0).reverse());for(const t of s)e.unshift(a(t))}else void 0!==t&&e.push(a(t));return e}static _$Eu(t,e){const s=e.attribute;return!1===s?void 0:"string"==typeof s?s:"string"==typeof t?t.toLowerCase():void 0}constructor(){super(),this._$Ep=void 0,this.isUpdatePending=!1,this.hasUpdated=!1,this._$Em=null,this._$Ev()}_$Ev(){this._$ES=new Promise(t=>this.enableUpdating=t),this._$AL=new Map,this._$E_(),this.requestUpdate(),this.constructor.l?.forEach(t=>t(this))}addController(t){(this._$EO??=new Set).add(t),void 0!==this.renderRoot&&this.isConnected&&t.hostConnected?.()}removeController(t){this._$EO?.delete(t)}_$E_(){const t=new Map,e=this.constructor.elementProperties;for(const s of e.keys())this.hasOwnProperty(s)&&(t.set(s,this[s]),delete this[s]);t.size>0&&(this._$Ep=t)}createRenderRoot(){const t=this.shadowRoot??this.attachShadow(this.constructor.shadowRootOptions);return r(t,this.constructor.elementStyles),t}connectedCallback(){this.renderRoot??=this.createRenderRoot(),this.enableUpdating(!0),this._$EO?.forEach(t=>t.hostConnected?.())}enableUpdating(t){}disconnectedCallback(){this._$EO?.forEach(t=>t.hostDisconnected?.())}attributeChangedCallback(t,e,s){this._$AK(t,s)}_$ET(t,e){const s=this.constructor.elementProperties.get(t),i=this.constructor._$Eu(t,s);if(void 0!==i&&!0===s.reflect){const n=(void 0!==s.converter?.toAttribute?s.converter:b).toAttribute(e,s.type);this._$Em=t,null==n?this.removeAttribute(i):this.setAttribute(i,n),this._$Em=null}}_$AK(t,e){const s=this.constructor,i=s._$Eh.get(t);if(void 0!==i&&this._$Em!==i){const t=s.getPropertyOptions(i),n="function"==typeof t.converter?{fromAttribute:t.converter}:void 0!==t.converter?.fromAttribute?t.converter:b;this._$Em=i;const o=n.fromAttribute(e,t.type);this[i]=o??this._$Ej?.get(i)??o,this._$Em=null}}requestUpdate(t,e,s,i=!1,n){if(void 0!==t){const o=this.constructor;if(!1===i&&(n=this[t]),s??=o.getPropertyOptions(t),!((s.hasChanged??y)(n,e)||s.useDefault&&s.reflect&&n===this._$Ej?.get(t)&&!this.hasAttribute(o._$Eu(t,s))))return;this.C(t,e,s)}!1===this.isUpdatePending&&(this._$ES=this._$EP())}C(t,e,{useDefault:s,reflect:i,wrapped:n},o){s&&!(this._$Ej??=new Map).has(t)&&(this._$Ej.set(t,o??e??this[t]),!0!==n||void 0!==o)||(this._$AL.has(t)||(this.hasUpdated||s||(e=void 0),this._$AL.set(t,e)),!0===i&&this._$Em!==t&&(this._$Eq??=new Set).add(t))}async _$EP(){this.isUpdatePending=!0;try{await this._$ES}catch(t){Promise.reject(t)}const t=this.scheduleUpdate();return null!=t&&await t,!this.isUpdatePending}scheduleUpdate(){return this.performUpdate()}performUpdate(){if(!this.isUpdatePending)return;if(!this.hasUpdated){if(this.renderRoot??=this.createRenderRoot(),this._$Ep){for(const[t,e]of this._$Ep)this[t]=e;this._$Ep=void 0}const t=this.constructor.elementProperties;if(t.size>0)for(const[e,s]of t){const{wrapped:t}=s,i=this[e];!0!==t||this._$AL.has(e)||void 0===i||this.C(e,void 0,s,i)}}let t=!1;const e=this._$AL;try{t=this.shouldUpdate(e),t?(this.willUpdate(e),this._$EO?.forEach(t=>t.hostUpdate?.()),this.update(e)):this._$EM()}catch(e){throw t=!1,this._$EM(),e}t&&this._$AE(e)}willUpdate(t){}_$AE(t){this._$EO?.forEach(t=>t.hostUpdated?.()),this.hasUpdated||(this.hasUpdated=!0,this.firstUpdated(t)),this.updated(t)}_$EM(){this._$AL=new Map,this.isUpdatePending=!1}get updateComplete(){return this.getUpdateComplete()}getUpdateComplete(){return this._$ES}shouldUpdate(t){return!0}update(t){this._$Eq&&=this._$Eq.forEach(t=>this._$ET(t,this[t])),this._$EM()}updated(t){}firstUpdated(t){}}A.elementStyles=[],A.shadowRootOptions={mode:"open"},A[_("elementProperties")]=new Map,A[_("finalized")]=new Map,$?.({ReactiveElement:A}),(g.reactiveElementVersions??=[]).push("2.1.2");const w=globalThis,E=t=>t,S=w.trustedTypes,C=S?S.createPolicy("lit-html",{createHTML:t=>t}):void 0,x="$lit$",P=`lit$${Math.random().toFixed(9).slice(2)}$`,k="?"+P,O=`<${k}>`,U=document,M=()=>U.createComment(""),D=t=>null===t||"object"!=typeof t&&"function"!=typeof t,R=Array.isArray,H="[ \t\n\f\r]",T=/<(?:(!--|\/[^a-zA-Z])|(\/?[a-zA-Z][^>\s]*)|(\/?$))/g,N=/-->/g,z=/>/g,I=RegExp(`>|${H}(?:([^\\s"'>=/]+)(${H}*=${H}*(?:[^ \t\n\f\r"'\`<>=]|("|')|))|$)`,"g"),j=/'/g,L=/"/g,B=/^(?:script|style|textarea|title)$/i,G=t=>(e,...s)=>({_$litType$:t,strings:e,values:s}),q=G(1),V=(G(2),G(3),Symbol.for("lit-noChange")),W=Symbol.for("lit-nothing"),F=new WeakMap,J=U.createTreeWalker(U,129);function Z(t,e){if(!R(t)||!t.hasOwnProperty("raw"))throw Error("invalid template strings array");return void 0!==C?C.createHTML(e):e}const K=(t,e)=>{const s=t.length-1,i=[];let n,o=2===e?"<svg>":3===e?"<math>":"",r=T;for(let e=0;e<s;e++){const s=t[e];let a,h,l=-1,c=0;for(;c<s.length&&(r.lastIndex=c,h=r.exec(s),null!==h);)c=r.lastIndex,r===T?"!--"===h[1]?r=N:void 0!==h[1]?r=z:void 0!==h[2]?(B.test(h[2])&&(n=RegExp("</"+h[2],"g")),r=I):void 0!==h[3]&&(r=I):r===I?">"===h[0]?(r=n??T,l=-1):void 0===h[1]?l=-2:(l=r.lastIndex-h[2].length,a=h[1],r=void 0===h[3]?I:'"'===h[3]?L:j):r===L||r===j?r=I:r===N||r===z?r=T:(r=I,n=void 0);const d=r===I&&t[e+1].startsWith("/>")?" ":"";o+=r===T?s+O:l>=0?(i.push(a),s.slice(0,l)+x+s.slice(l)+P+d):s+P+(-2===l?e:d)}return[Z(t,o+(t[s]||"<?>")+(2===e?"</svg>":3===e?"</math>":"")),i]};class Y{constructor({strings:t,_$litType$:e},s){let i;this.parts=[];let n=0,o=0;const r=t.length-1,a=this.parts,[h,l]=K(t,e);if(this.el=Y.createElement(h,s),J.currentNode=this.el.content,2===e||3===e){const t=this.el.content.firstChild;t.replaceWith(...t.childNodes)}for(;null!==(i=J.nextNode())&&a.length<r;){if(1===i.nodeType){if(i.hasAttributes())for(const t of i.getAttributeNames())if(t.endsWith(x)){const e=l[o++],s=i.getAttribute(t).split(P),r=/([.?@])?(.*)/.exec(e);a.push({type:1,index:n,name:r[2],strings:s,ctor:"."===r[1]?st:"?"===r[1]?it:"@"===r[1]?nt:et}),i.removeAttribute(t)}else t.startsWith(P)&&(a.push({type:6,index:n}),i.removeAttribute(t));if(B.test(i.tagName)){const t=i.textContent.split(P),e=t.length-1;if(e>0){i.textContent=S?S.emptyScript:"";for(let s=0;s<e;s++)i.append(t[s],M()),J.nextNode(),a.push({type:2,index:++n});i.append(t[e],M())}}}else if(8===i.nodeType)if(i.data===k)a.push({type:2,index:n});else{let t=-1;for(;-1!==(t=i.data.indexOf(P,t+1));)a.push({type:7,index:n}),t+=P.length-1}n++}}static createElement(t,e){const s=U.createElement("template");return s.innerHTML=t,s}}function Q(t,e,s=t,i){if(e===V)return e;let n=void 0!==i?s._$Co?.[i]:s._$Cl;const o=D(e)?void 0:e._$litDirective$;return n?.constructor!==o&&(n?._$AO?.(!1),void 0===o?n=void 0:(n=new o(t),n._$AT(t,s,i)),void 0!==i?(s._$Co??=[])[i]=n:s._$Cl=n),void 0!==n&&(e=Q(t,n._$AS(t,e.values),n,i)),e}class X{constructor(t,e){this._$AV=[],this._$AN=void 0,this._$AD=t,this._$AM=e}get parentNode(){return this._$AM.parentNode}get _$AU(){return this._$AM._$AU}u(t){const{el:{content:e},parts:s}=this._$AD,i=(t?.creationScope??U).importNode(e,!0);J.currentNode=i;let n=J.nextNode(),o=0,r=0,a=s[0];for(;void 0!==a;){if(o===a.index){let e;2===a.type?e=new tt(n,n.nextSibling,this,t):1===a.type?e=new a.ctor(n,a.name,a.strings,this,t):6===a.type&&(e=new ot(n,this,t)),this._$AV.push(e),a=s[++r]}o!==a?.index&&(n=J.nextNode(),o++)}return J.currentNode=U,i}p(t){let e=0;for(const s of this._$AV)void 0!==s&&(void 0!==s.strings?(s._$AI(t,s,e),e+=s.strings.length-2):s._$AI(t[e])),e++}}class tt{get _$AU(){return this._$AM?._$AU??this._$Cv}constructor(t,e,s,i){this.type=2,this._$AH=W,this._$AN=void 0,this._$AA=t,this._$AB=e,this._$AM=s,this.options=i,this._$Cv=i?.isConnected??!0}get parentNode(){let t=this._$AA.parentNode;const e=this._$AM;return void 0!==e&&11===t?.nodeType&&(t=e.parentNode),t}get startNode(){return this._$AA}get endNode(){return this._$AB}_$AI(t,e=this){t=Q(this,t,e),D(t)?t===W||null==t||""===t?(this._$AH!==W&&this._$AR(),this._$AH=W):t!==this._$AH&&t!==V&&this._(t):void 0!==t._$litType$?this.$(t):void 0!==t.nodeType?this.T(t):(t=>R(t)||"function"==typeof t?.[Symbol.iterator])(t)?this.k(t):this._(t)}O(t){return this._$AA.parentNode.insertBefore(t,this._$AB)}T(t){this._$AH!==t&&(this._$AR(),this._$AH=this.O(t))}_(t){this._$AH!==W&&D(this._$AH)?this._$AA.nextSibling.data=t:this.T(U.createTextNode(t)),this._$AH=t}$(t){const{values:e,_$litType$:s}=t,i="number"==typeof s?this._$AC(t):(void 0===s.el&&(s.el=Y.createElement(Z(s.h,s.h[0]),this.options)),s);if(this._$AH?._$AD===i)this._$AH.p(e);else{const t=new X(i,this),s=t.u(this.options);t.p(e),this.T(s),this._$AH=t}}_$AC(t){let e=F.get(t.strings);return void 0===e&&F.set(t.strings,e=new Y(t)),e}k(t){R(this._$AH)||(this._$AH=[],this._$AR());const e=this._$AH;let s,i=0;for(const n of t)i===e.length?e.push(s=new tt(this.O(M()),this.O(M()),this,this.options)):s=e[i],s._$AI(n),i++;i<e.length&&(this._$AR(s&&s._$AB.nextSibling,i),e.length=i)}_$AR(t=this._$AA.nextSibling,e){for(this._$AP?.(!1,!0,e);t!==this._$AB;){const e=E(t).nextSibling;E(t).remove(),t=e}}setConnected(t){void 0===this._$AM&&(this._$Cv=t,this._$AP?.(t))}}class et{get tagName(){return this.element.tagName}get _$AU(){return this._$AM._$AU}constructor(t,e,s,i,n){this.type=1,this._$AH=W,this._$AN=void 0,this.element=t,this.name=e,this._$AM=i,this.options=n,s.length>2||""!==s[0]||""!==s[1]?(this._$AH=Array(s.length-1).fill(new String),this.strings=s):this._$AH=W}_$AI(t,e=this,s,i){const n=this.strings;let o=!1;if(void 0===n)t=Q(this,t,e,0),o=!D(t)||t!==this._$AH&&t!==V,o&&(this._$AH=t);else{const i=t;let r,a;for(t=n[0],r=0;r<n.length-1;r++)a=Q(this,i[s+r],e,r),a===V&&(a=this._$AH[r]),o||=!D(a)||a!==this._$AH[r],a===W?t=W:t!==W&&(t+=(a??"")+n[r+1]),this._$AH[r]=a}o&&!i&&this.j(t)}j(t){t===W?this.element.removeAttribute(this.name):this.element.setAttribute(this.name,t??"")}}class st extends et{constructor(){super(...arguments),this.type=3}j(t){this.element[this.name]=t===W?void 0:t}}class it extends et{constructor(){super(...arguments),this.type=4}j(t){this.element.toggleAttribute(this.name,!!t&&t!==W)}}class nt extends et{constructor(t,e,s,i,n){super(t,e,s,i,n),this.type=5}_$AI(t,e=this){if((t=Q(this,t,e,0)??W)===V)return;const s=this._$AH,i=t===W&&s!==W||t.capture!==s.capture||t.once!==s.once||t.passive!==s.passive,n=t!==W&&(s===W||i);i&&this.element.removeEventListener(this.name,this,s),n&&this.element.addEventListener(this.name,this,t),this._$AH=t}handleEvent(t){"function"==typeof this._$AH?this._$AH.call(this.options?.host??this.element,t):this._$AH.handleEvent(t)}}class ot{constructor(t,e,s){this.element=t,this.type=6,this._$AN=void 0,this._$AM=e,this.options=s}get _$AU(){return this._$AM._$AU}_$AI(t){Q(this,t)}}const rt=w.litHtmlPolyfillSupport;rt?.(Y,tt),(w.litHtmlVersions??=[]).push("3.3.3");const at=(t,e,s)=>{const i=s?.renderBefore??e;let n=i._$litPart$;if(void 0===n){const t=s?.renderBefore??null;i._$litPart$=n=new tt(e.insertBefore(M(),t),t,void 0,s??{})}return n._$AI(t),n},ht=globalThis;class lt extends A{constructor(){super(...arguments),this.renderOptions={host:this},this._$Do=void 0}createRenderRoot(){const t=super.createRenderRoot();return this.renderOptions.renderBefore??=t.firstChild,t}update(t){const e=this.render();this.hasUpdated||(this.renderOptions.isConnected=this.isConnected),super.update(t),this._$Do=at(e,this.renderRoot,this.renderOptions)}connectedCallback(){super.connectedCallback(),this._$Do?.setConnected(!0)}disconnectedCallback(){super.disconnectedCallback(),this._$Do?.setConnected(!1)}render(){return V}}lt._$litElement$=!0,lt.finalized=!0,ht.litElementHydrateSupport?.({LitElement:lt});const ct=ht.litElementPolyfillSupport;ct?.({LitElement:lt}),(ht.litElementVersions??=[]).push("4.2.2");class dt{constructor(){}static getInstance(){return dt.instance||(dt.instance=new dt),dt.instance}getItem(t){try{if("undefined"!=typeof window&&window.localStorage)return window.localStorage.getItem(t)}catch{}return null}setItem(t,e){try{"undefined"!=typeof window&&window.localStorage&&window.localStorage.setItem(t,e)}catch{}}removeItem(t){try{"undefined"!=typeof window&&window.localStorage&&window.localStorage.removeItem(t)}catch{}}clearAllData(){try{"undefined"!=typeof window&&(window.localStorage&&window.localStorage.clear(),window.sessionStorage&&window.sessionStorage.clear())}catch(t){console.error("Fehler beim Löschen des lokalen Speichers:",t)}}getOnboardingConsent(){const t=this.getItem("ecochef_gdpr_consent");if(!t)return null;try{return JSON.parse(t)}catch{return null}}saveOnboardingConsent(t){this.setItem("ecochef_gdpr_consent",JSON.stringify({...t,consentTimestamp:(new Date).toISOString()}))}}const pt=dt.getInstance();class ut extends lt{constructor(){super(...arguments),this.healthConsent=!1,this.geminiConsent=!1}static{this.styles=o`
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
  `}static{this.properties={healthConsent:{type:Boolean},geminiConsent:{type:Boolean}}}handleHealthChange(t){this.healthConsent=t.target.checked,this.requestUpdate()}handleGeminiChange(t){this.geminiConsent=t.target.checked,this.requestUpdate()}handleSaveConsent(){this.healthConsent&&this.geminiConsent&&(pt.saveOnboardingConsent({healthDataAccepted:this.healthConsent,geminiDataAccepted:this.geminiConsent}),this.dispatchEvent(new CustomEvent("onboarding-completed",{detail:{healthConsent:this.healthConsent,geminiConsent:this.geminiConsent},bubbles:!0,composed:!0})))}handleClearAllData(){confirm("Möchtest du wirklich alle lokalen Daten unwiderruflich löschen?")&&(pt.clearAllData(),this.healthConsent=!1,this.geminiConsent=!1,this.requestUpdate(),alert("Alle Daten wurden vollständig aus dem lokalen Speicher gelöscht."),this.dispatchEvent(new CustomEvent("data-cleared",{bubbles:!0,composed:!0})))}render(){const t=this.healthConsent&&this.geminiConsent;return q`
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
            ?disabled=${!t}
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
    `}}customElements.get("eco-onboarding-screen")||customElements.define("eco-onboarding-screen",ut);const gt={attribute:!0,type:String,converter:b,reflect:!1,hasChanged:y},mt=(t=gt,e,s)=>{const{kind:i,metadata:n}=s;let o=globalThis.litPropertyMetadata.get(n);if(void 0===o&&globalThis.litPropertyMetadata.set(n,o=new Map),"setter"===i&&((t=Object.create(t)).wrapped=!0),o.set(s.name,t),"accessor"===i){const{name:i}=s;return{set(s){const n=e.get.call(this);e.set.call(this,s),this.requestUpdate(i,n,t,!0,s)},init(e){return void 0!==e&&this.C(i,void 0,t,e),e}}}if("setter"===i){const{name:i}=s;return function(s){const n=this[i];e.call(this,s),this.requestUpdate(i,n,t,!0,s)}}throw Error("Unsupported decorator location: "+i)};var ft=function(t,e,s,i){var n,o=arguments.length,r=o<3?e:null===i?i=Object.getOwnPropertyDescriptor(e,s):i;if("object"==typeof Reflect&&"function"==typeof Reflect.decorate)r=Reflect.decorate(t,e,s,i);else for(var a=t.length-1;a>=0;a--)(n=t[a])&&(r=(o<3?n(r):o>3?n(e,s,r):n(e,s))||r);return o>3&&r&&Object.defineProperty(e,s,r),r};let $t=class extends lt{constructor(){super(...arguments),this.active=!1,this.handlePointerMove=t=>{this.active&&(this.style.top=`${t.clientY}px`)}}static{this.styles=o`
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
  `}connectedCallback(){super.connectedCallback(),window.addEventListener("pointermove",this.handlePointerMove,{passive:!0})}disconnectedCallback(){window.removeEventListener("pointermove",this.handlePointerMove),super.disconnectedCallback()}render(){return q``}};ft([function(t){return(e,s)=>"object"==typeof s?mt(t,e,s):((t,e,s)=>{const i=e.hasOwnProperty(s);return e.constructor.createProperty(s,t),i?Object.getOwnPropertyDescriptor(e,s):void 0})(t,e,s)}({type:Boolean,reflect:!0})],$t.prototype,"active",void 0),$t=ft([(t=>(e,s)=>{void 0!==s?s.addInitializer(()=>{customElements.define(t,e)}):customElements.define(t,e)})("reading-ruler")],$t);const _t=q`
  <onboarding-screen></onboarding-screen>
  <reading-ruler></reading-ruler>
`,bt=document.getElementById("app");bt?at(_t,bt):console.error("Kritischer Fehler: App-Root-Element (#app) nicht in index.html gefunden.")})();
//# sourceMappingURL=bundle.ae537a4f.js.map