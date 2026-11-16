// Offline orthographic triangle rasterizer. Display-only depth testing keeps
// rear wall triangles from drawing over a roof because of centroid ordering.
function depthRender(ctx, faces, dpr, wireframe, edges) {
  const width=ctx.canvas.width,height=ctx.canvas.height;
  const pixels=ctx.createImageData(width,height),rgba=pixels.data;
  const depth=new Float64Array(width*height);depth.fill(-Infinity);
  let drawnFaces=0,drawnEdges=0;
  const projected=faces.map(rf=>{
    const p=rf.f.map(k=>[rf.ps[k][0]*dpr,rf.ps[k][1]*dpr,rf.ps[k][2]]);
    const rgb=shade(rf.g.normals[rf.i],rf.g.roles[rf.i]).match(/\d+/g).map(Number);
    return {rf,p,rgb};
  });
  for(const {p,rgb} of projected){
    // Measured meshes contain triangles; the fan also handles convex faces.
    for(let j=1;j<p.length-1;j++){
      const [a,b,c]=[p[0],p[j],p[j+1]];
      const den=(b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1]);
      if(Math.abs(den)<1e-12)continue;
      const x0=Math.max(0,Math.floor(Math.min(a[0],b[0],c[0]))),x1=Math.min(width-1,Math.ceil(Math.max(a[0],b[0],c[0])));
      const y0=Math.max(0,Math.floor(Math.min(a[1],b[1],c[1]))),y1=Math.min(height-1,Math.ceil(Math.max(a[1],b[1],c[1])));
      for(let y=y0;y<=y1;y++)for(let x=x0;x<=x1;x++){
        const u=((b[1]-c[1])*(x+.5-c[0])+(c[0]-b[0])*(y+.5-c[1]))/den;
        const v=((c[1]-a[1])*(x+.5-c[0])+(a[0]-c[0])*(y+.5-c[1]))/den,w=1-u-v;
        if(Math.min(u,v,w)<-1e-9)continue;
        const z=u*a[2]+v*b[2]+w*c[2],idx=y*width+x;
        if(z<depth[idx]-1e-8)continue;
        const off=idx*4;
        // Deterministic tie at an exact shared edge/intersection, independent
        // of input face order. This affects only equal-depth colour selection.
        if(Math.abs(z-depth[idx])<=1e-8 && rgb[0]*65536+rgb[1]*256+rgb[2]>=rgba[off]*65536+rgba[off+1]*256+rgba[off+2])continue;
        depth[idx]=z;
        rgba[off]=rgb[0];rgba[off+1]=rgb[1];rgba[off+2]=rgb[2];rgba[off+3]=255;
      }
    }
    drawnFaces++;
  }
  function line(a,b,alpha,lineWidth){
    const n=Math.max(1,Math.ceil(Math.hypot(b[0]-a[0],b[1]-a[1])*1.5));
    const radius=Math.max(.45,lineWidth*dpr/2);
    for(let i=0;i<=n;i++){
      const t=i/n,px=a[0]+(b[0]-a[0])*t,py=a[1]+(b[1]-a[1])*t,z=a[2]+(b[2]-a[2])*t;
      for(let y=Math.max(0,Math.floor(py-radius));y<=Math.min(height-1,Math.ceil(py+radius));y++)
      for(let x=Math.max(0,Math.floor(px-radius));x<=Math.min(width-1,Math.ceil(px+radius));x++){
        if(Math.hypot(x+.5-px,y+.5-py)>radius)continue;
        const idx=y*width+x;
        // The line sample and pixel centre differ by a fraction of a pixel.
        const tolerance=.02+Math.abs(b[2]-a[2])/Math.max(1,Math.hypot(b[0]-a[0],b[1]-a[1]));
        if(z<depth[idx]-tolerance)continue;
        const off=idx*4;
        if(!rgba[off+3]){rgba[off]=47;rgba[off+1]=57;rgba[off+2]=49;rgba[off+3]=Math.round(255*alpha);}
        else {rgba[off]=Math.round(rgba[off]*(1-alpha)+47*alpha);rgba[off+1]=Math.round(rgba[off+1]*(1-alpha)+57*alpha);rgba[off+2]=Math.round(rgba[off+2]*(1-alpha)+49*alpha);}
      }
    }
  }
  for(const {rf,p} of projected){
    if(wireframe){for(let i=0;i<p.length;i++)line(p[i],p[(i+1)%p.length],.3,.45);drawnEdges+=p.length;}
    else if(edges&&rf.g.roles[rf.i]!=='ground'){
      for(const e of rf.g.byFace[rf.i]){
        const a=rf.ps[e.a].map((v,k)=>k<2?v*dpr:v),b=rf.ps[e.b].map((v,k)=>k<2?v*dpr:v);
        const lo=e.t0??0,hi=e.t1??1;
        line(a.map((v,k)=>v+(b[k]-v)*lo),a.map((v,k)=>v+(b[k]-v)*hi),.62,.85);drawnEdges++;
      }
    }
  }
  ctx.putImageData(pixels,0,0);
  return {drawnFaces,drawnEdges};
}
