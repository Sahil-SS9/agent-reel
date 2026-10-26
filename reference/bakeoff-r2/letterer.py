"""Scrollback Reel bake-off letterer (r2). Places balloons using vision-detected head boxes."""
import json, math, os, sys, textwrap
from PIL import Image, ImageDraw, ImageFont
BASE="~/handoffs/agent-story-replay/bakeoff-gpt-image/"
FONT=BASE+"fonts/ComicNeue-Bold.ttf"; BANG=BASE+"fonts/Bangers-Regular.ttf"
F2=ImageFont.truetype(FONT,38); FCAP=ImageFont.truetype(FONT,30); FC=ImageFont.truetype(FONT,32)
FT=ImageFont.truetype(BANG,120); FS=ImageFont.truetype(BANG,48)
EP=json.load(open(BASE+"r2/episode.json")); V,S=EP["layout"],EP["script"]
RAW=BASE+"r2/raw/"; OUT=BASE+"r2/out/"
def px(b,W,H): return [b[0]*W,b[1]*H,b[2]*W,b[3]*H]
def inter(a,b):
    w=min(a[2],b[2])-max(a[0],b[0]); h=min(a[3],b[3])-max(a[1],b[1]); return max(0,w)*max(0,h)
def pad(b,e): return [b[0]-e,b[1]-e,b[2]+e,b[3]+e]
def letter(style,p):
    im=Image.open(RAW+f"{style}_{p}.png").convert("RGB"); d=ImageDraw.Draw(im); W,H=im.size
    v=V[style][p]; s=S[p]
    heads=[px(v[k],W,H) for k in ("sahil","kensei","holo") if v.get(k)]
    blocked=[pad(h,18) for h in heads]+[pad(px(k,W,H),10) for k in v.get("keep_out",[])]; free=[px(f,W,H) for f in v["free"]]
    cb=d.textbbox((0,0),s["cap"],font=FCAP); cw,ch=cb[2]-cb[0]+36,cb[3]-cb[1]+26
    capbox=[0,0,cw,ch]
    if any(inter(capbox,b)>0 for b in blocked): capbox=[0,H-ch,cw,H]
    placed=[capbox]; prev_top=None; prev_right=0
    for spk,txt in s["lines"]:
        h=px(v[spk],W,H); hx,hy=(h[0]+h[2])/2,h[1]
        best=None
        for fsz in (38,34,30):
            fnt=ImageFont.truetype(FONT,fsz)
            for wrapw in (14,18,22,28,34):
                wrapped_c=textwrap.fill(txt,wrapw)
                tb=d.multiline_textbbox((0,0),wrapped_c,font=fnt,spacing=4,align="center")
                tw,th=tb[2]-tb[0],tb[3]-tb[1]; bw,bh=int(tw*1.32+50),int(th*1.45+40)
                for x in range(10,W-bw-10,16):
                    for y in range(10,H-bh-10,16):
                        if prev_top is not None and not (y >= prev_top+30 or (abs(y-prev_top)<=60 and x >= prev_right-20)): continue
                        box=[x,y,x+bw,y+bh]
                        if any(inter(box,b)>0 for b in blocked+placed): continue
                        ff=sum(inter(box,f) for f in free)/(bw*bh)
                        dist=math.hypot(x+bw/2-hx,(y+bh-hy)*1.3)
                        sc=1.6*dist+900*(1-min(ff,1))+(400 if y+bh>hy+40 else 0)+8*(38-fsz)
                        if best is None or sc<best[0]: best=(sc,box,wrapped_c,fnt,bw,bh)
        if best is None: print("NO SPOT",style,p,spk); continue
        print("DBG",style,p,spk,[int(t) for t in best[1]],best[3].size) if os.environ.get("DBG") else None
        box,wrapped,F2,bw,bh=best[1:]; placed.append(box); prev_top=box[1]; prev_right=box[2]
        cx,cy=(box[0]+box[2])/2,(box[1]+box[3])/2
        tx,ty=(hx,(h[1]+h[3])/2) if spk=="holo" else (hx,h[1]+(h[3]-h[1])*0.55)
        ang=math.atan2(ty-cy,tx-cx)
        ex,ey=cx+(bw/2)*math.cos(ang),cy+(bh/2)*math.sin(ang)
        L=math.hypot(tx-ex,ty-ey); tl=min(max(L-(h[3]-h[1])*0.35,30),480)
        tip=(ex+tl*math.cos(ang),ey+tl*math.sin(ang)); perp=ang+math.pi/2; bwid=26
        b1=(cx+(bw/2-30)*math.cos(ang)+bwid*math.cos(perp),cy+(bh/2-20)*math.sin(ang)+bwid*math.sin(perp))
        b2=(cx+(bw/2-30)*math.cos(ang)-bwid*math.cos(perp),cy+(bh/2-20)*math.sin(ang)-bwid*math.sin(perp))
        fill="#e8fbff" if spk=="holo" else "white"
        d.polygon([b1,b2,tip],fill=fill,outline="black",width=4)
        if spk=="holo": d.rounded_rectangle(box,radius=18,fill=fill,outline="black",width=5)
        else: d.ellipse(box,fill=fill,outline="black",width=5)
        d.polygon([(b1[0]*.9+tip[0]*.1,b1[1]*.9+tip[1]*.1),(b2[0]*.9+tip[0]*.1,b2[1]*.9+tip[1]*.1),(cx,cy)],fill=fill)
        d.multiline_text((cx,cy),wrapped,font=F2,fill="black",anchor="mm",spacing=4,align="center")
    d.rectangle(capbox,fill="#fff3b0",outline="black",width=4); d.text((capbox[0]+18,capbox[1]+10),s["cap"],font=FCAP,fill="black")
    if "sfx" in s:
        best=None; sw,sh=330,140
        for x in range(20,W-sw-20,20):
            for y in (int(H*.5),int(H*.6),int(H*.7)):
                box=[x,y,x+sw,y+sh]
                if any(inter(box,b)>0 for b in blocked+placed): continue
                sc=abs(x-W*.15)
                if best is None or sc<best[0]: best=(sc,box)
        if best:
            layer=Image.new("RGBA",(sw+80,sh+80),(0,0,0,0)); ld=ImageDraw.Draw(layer)
            ld.text((40,30),s["sfx"],font=ImageFont.truetype(BANG,130),fill="#ffdd00" if style=="anime" else "white",stroke_width=8,stroke_fill="black")
            layer=layer.rotate(12,expand=True); im.paste(layer,(best[1][0],best[1][1]),layer)
    return im
def compose(panels,cols,title,out,footer):
    pw,ph=panels[0].size; g=24; head=220; foot=130; rows=(len(panels)+cols-1)//cols
    W=cols*pw+(cols+1)*g; H=head+rows*ph+(rows+1)*g+foot
    pg=Image.new("RGB",(W,H),"white"); d=ImageDraw.Draw(pg)
    d.text((W/2,head/2+10),title,font=FT,fill="black",anchor="mm")
    for i,p in enumerate(panels):
        r,c=divmod(i,cols); x=g+c*(pw+g); y=head+g+r*(ph+g); pg.paste(p,(x,y)); d.rectangle([x,y,x+pw,y+ph],outline="black",width=8)
    d.text((W-g,H-foot/2),footer,font=FS,fill="black",anchor="rm")
    d.text((g,H-foot/2),"Hermes Scrollback Reel · Ep.1 'The Orphans' · GPT Image 2 · private bake-off r2",font=FC,fill="#555",anchor="lm")
    pg.save(out,quality=88,optimize=True)
if __name__=="__main__":
    os.makedirs(OUT,exist_ok=True)
    for style in ("anime","ink"):
        ps=[letter(style,p) for p in ("p1","p2","p3","p4","p5","p6")]
        for i,p in enumerate(ps): p.save(OUT+f"{style}_panel{i+1}.jpg",quality=90)
        t="SCROLLBACK REEL · EP.1: THE ORPHANS"; f="NEXT WEEK: THE ORPHANS RETURN?"
        compose(ps,2,t,OUT+f"{style}_page_2x3.jpg",f); compose(ps,3,t,OUT+f"{style}_x_3x2.jpg",f)
        compose(ps,1,"SCROLLBACK REEL · EP.1",OUT+f"{style}_vertical_strip.jpg",f)
    print("done")
