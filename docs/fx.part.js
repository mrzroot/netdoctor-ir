(function(){var hero=FX.$('.hero');if(!hero)return;var cv=FX.layer(hero),buf=[],X=0,beat=0,mode=0,modeT=0,msgs=['DNS HIJACK','SNI FILTERED','403 SANCTION','MIRROR OK','TLS RESET'],roll=document.createElement('div');roll.className='crt-roll';roll.setAttribute('aria-hidden','true');hero.appendChild(roll);
function y(ph,amp){/* one PQRST-ish beat, ph in 0..1 */if(ph<.1)return Math.sin(ph/.1*Math.PI)*amp*.12;if(ph<.18)return 0;if(ph<.22)return -(ph-.18)/.04*amp*.15;if(ph<.26)return (-.15+(ph-.22)/.04*1.5)*amp*(-1)*-1*-1;if(ph<.30)return amp*(1.35-(ph-.26)/.04*2.1);if(ph<.34)return amp*(-.75+(ph-.30)/.04*.75);if(ph<.5)return 0;if(ph<.62)return -Math.sin((ph-.5)/.12*Math.PI)*amp*.22;return 0}
FX.loop(cv,function(c,w,h,t,dt,m){c.clearRect(0,0,w,h);var D=FX.theme()==='dark',col=D?'51,255,122':'11,122,58',mid=w<600?44:70,amp=w<600?34:52;
 if(mode===1){modeT-=dt;if(modeT<=0)mode=0}
 var sp=w<600?150:230,n=Math.ceil(sp*dt);beat+=dt*(mode?3.1:.85);if(beat>1)beat-=1;
 var v=mode?(Math.sin(t*38)*amp*.7*(Math.random()<.2?1.4:.6)):y(beat,amp);buf.push(v);var cap=Math.ceil(w/ (sp/60))+4;while(buf.length>cap)buf.shift();
 /* grid */
 c.strokeStyle='rgba('+col+',.07)';c.lineWidth=1;c.beginPath();for(var gx=0;gx<w;gx+=40){c.moveTo(gx,0);c.lineTo(gx,h)}for(var gy=0;gy<h;gy+=40){c.moveTo(0,gy);c.lineTo(w,gy)}c.stroke();
 var st=sp/60;c.lineWidth=2.4;c.lineJoin='round';var bad=mode===1;
 for(var pass=0;pass<2;pass++){c.beginPath();for(var i=0;i<buf.length;i++){var px=w-(buf.length-1-i)*st,py=mid-buf[i];i?c.lineTo(px,py):c.moveTo(px,py)}
  c.strokeStyle=pass?(bad?'rgba(255,75,75,.95)':'rgba('+col+',.95)'):(bad?'rgba(255,75,75,.25)':'rgba('+col+',.25)');c.lineWidth=pass?2.2:7;if(D||pass)c.stroke()}
 var hx=w,hy=mid-(buf[buf.length-1]||0);c.fillStyle=bad?'#ff4b4b':'rgba('+col+',1)';c.beginPath();c.arc(hx-4,hy,4,0,6.3);c.fill();
},{still:2,dpr:1.5});
function diag(x,y,txt,bad){var d=document.createElement('div');d.className='diag';d.textContent=txt;d.style.left=Math.max(8,Math.min(x,hero.clientWidth-200))+'px';d.style.top=y+'px';d.style.color=bad?'#ff4b4b':'var(--accent)';hero.appendChild(d);setTimeout(function(){d.remove()},2500)}
hero.addEventListener('pointerdown',function(e){if(e.target.closest('a,button,code,.install,pre,.term'))return;var r=hero.getBoundingClientRect();mode=1;modeT=1.6;diag(e.clientX-r.left,e.clientY-r.top,'! '+msgs[(Math.random()*4)|0],true);setTimeout(function(){diag(e.clientX-r.left,e.clientY-r.top+26,'> '+msgs[3],false)},1700)});
FX.reveal('.card,.step');
})();
