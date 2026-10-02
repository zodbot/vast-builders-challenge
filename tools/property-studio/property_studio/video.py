"""Render a narrated portrait MP4 from authorized photos and audited scenes."""
import json
import os
from pathlib import Path
import subprocess
import sys
import wave
import httpx
from PIL import Image,ImageDraw,ImageFont,ImageOps
from .adapters import ProviderError
from .story import audit

VOICE='en_US-ljspeech-medium'
VOICE_BASE='https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ljspeech/medium/'


def ensure_voice(root):
    root.mkdir(parents=True,exist_ok=True)
    for name in [VOICE+'.onnx',VOICE+'.onnx.json','MODEL_CARD']:
        target=root/name
        if target.exists(): continue
        temp=target.with_suffix(target.suffix+'.tmp')
        try:
            with httpx.stream('GET',VOICE_BASE+name,follow_redirects=True,timeout=90) as response:
                response.raise_for_status()
                with temp.open('wb') as f:
                    total=0
                    for chunk in response.iter_bytes():
                        total+=len(chunk)
                        if total>100_000_000: raise ValueError('Voice model exceeds budget')
                        f.write(chunk)
            temp.replace(target)
        except Exception:
            temp.unlink(missing_ok=True)
            raise ProviderError('Narration voice download failed; script and workbook remain available') from None
    return root/(VOICE+'.onnx')


def font(size):
    for path in ['/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf','/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf']:
        if Path(path).exists(): return ImageFont.truetype(path,size)
    return ImageFont.load_default(size=size)


def wrap(draw,text,typeface,width):
    lines=[];line=''
    for word in text.split():
        candidate=(line+' '+word).strip()
        if draw.textlength(candidate,font=typeface)>width and line: lines.append(line);line=word
        else: line=candidate
    if line: lines.append(line)
    return lines


def card(run,scene,photo,index,total,path):
    im=Image.new('RGB',(720,1280),'#112a26');draw=ImageDraw.Draw(im)
    draw.text((32,24),'PROPERTY STUDIO / '+('SYNTHETIC DEMO' if run.request.mode=='synthetic' else 'LISTING STORY'),font=font(17),fill='#d7eaa3')
    for i,line in enumerate(wrap(draw,run.property.address.split(',')[0],font(27),650)[:2]): draw.text((32,53+i*31),line,font=font(27),fill='white')
    with Image.open(photo) as source:
        fitted=ImageOps.contain(source.convert('RGB'),(720,720))
        im.paste(fitted,((720-fitted.width)//2,130+(720-fitted.height)//2))
    draw=ImageDraw.Draw(im)
    for i,line in enumerate(wrap(draw,scene.overlay or 'The listing. The numbers. The decision.',font(32),648)[:3]): draw.text((36,873+i*39),line,font=font(32),fill='#d7eaa3')
    size=24
    while len(wrap(draw,scene.narration,font(size),648))>7 and size>16: size-=1
    for i,line in enumerate(wrap(draw,scene.narration,font(size),648)):
        draw.text((36,1010+i*(size+4)),line,font=font(size),fill='white')
    draw.rectangle((32,1250,32+int(656*(index+1)/total),1254),fill='#d7eaa3')
    draw.text((32,1260),'AI NARRATION · EDITABLE SCENARIO · DRAFT',font=font(12),fill='#a1bcb0')
    im.save(path)


def render_video(run,folder,settings):
    if not run.story: raise ProviderError('Generate a script before rendering video')
    blocks=[f['message'] for f in audit(run) if f['severity']=='block']
    if blocks: raise ProviderError('Video needs a consistent script: '+blocks[0])
    if not any(m.permission!='review_required' for m in run.media): raise ProviderError('A listing photo is needed for video; script and workbook are available')
    folder=Path(folder);work=folder/'video-work';work.mkdir(exist_ok=True)
    model=ensure_voice(settings.data_dir/'runtime'/VOICE)
    path=work/'render.json';path.write_text(json.dumps({'run':run.model_dump(mode='json'),'folder':str(folder),'model':str(model)}))
    try:
        result=subprocess.run([sys.executable,'-m','property_studio.video',str(path)],capture_output=True,text=True,timeout=600,
                              env={**os.environ,'OMP_NUM_THREADS':'2','OPENBLAS_NUM_THREADS':'2'})
    except subprocess.TimeoutExpired: raise ProviderError('Video exceeded its rendering budget; script and Excel remain available') from None
    if result.returncode:
        (work/'error.txt').write_text(result.stderr[-3000:])
        raise ProviderError('Video rendering failed; inspect video-work/error.txt')
    run.artifacts['video']='listing-video.mp4';run.artifacts['captions']='captions.srt'
    return 'Narrated portrait MP4 and captions rendered from listing photos.'


def timestamp(seconds):
    ms=round(seconds*1000);h,ms=divmod(ms,3600000);m,ms=divmod(ms,60000);s,ms=divmod(ms,1000)
    return f'{h:02}:{m:02}:{s:02},{ms:03}'


def worker(path):
    import imageio_ffmpeg
    import onnxruntime
    from piper import PiperVoice,SynthesisConfig
    from piper.config import PiperConfig
    from .models import Run
    spec=json.loads(Path(path).read_text());run=Run.model_validate(spec['run']);folder=Path(spec['folder']);work=folder/'video-work'
    options=onnxruntime.SessionOptions()
    options.intra_op_num_threads=2;options.inter_op_num_threads=1
    voice=PiperVoice(config=PiperConfig.from_dict(json.loads(Path(spec['model']+'.json').read_text())),
                     session=onnxruntime.InferenceSession(spec['model'],sess_options=options,providers=['CPUExecutionProvider']))
    ffmpeg=imageio_ffmpeg.get_ffmpeg_exe()
    media={m.id:m for m in run.media if m.permission!='review_required'}
    clips=[];captions=[];timings=[];elapsed=0
    for i,scene in enumerate(run.story.scenes[:12]):
        audio=work/f'scene-{i}.wav'
        with wave.open(str(audio),'wb') as wav: voice.synthesize_wav(scene.narration,wav,syn_config=SynthesisConfig(length_scale=.93))
        with wave.open(str(audio),'rb') as wav: duration=wav.getnframes()/wav.getframerate()+.3
        item=next((media[mid] for mid in scene.media_ids if mid in media),list(media.values())[i%len(media)])
        frame=work/f'scene-{i}.png';card(run,scene,folder/item.filename,i,len(run.story.scenes),frame)
        clip=work/f'scene-{i}.mp4'
        subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-y','-loop','1','-framerate','24','-i',str(frame),'-i',str(audio),
              '-t',str(duration),'-vf','scale=720:1280,format=yuv420p','-c:v','libx264','-preset','veryfast','-crf','23','-threads','2',
              '-c:a','aac','-b:a','128k','-af','apad','-movflags','+faststart',str(clip)],check=True,timeout=90)
        clips.append(clip);captions.append(f'{i+1}\n{timestamp(elapsed)} --> {timestamp(elapsed+duration)}\n{scene.narration}\n')
        timings.append({'scene':i+1,'start':elapsed,'duration':duration,'media_id':item.id});elapsed+=duration
    playlist=work/'concat.txt';playlist.write_text(''.join("file '"+p.name+"'\n" for p in clips))
    output=folder/'listing-video.tmp.mp4'
    subprocess.run([ffmpeg,'-hide_banner','-loglevel','error','-y','-f','concat','-safe','0','-i',str(playlist),'-c','copy','-movflags','+faststart',str(output)],check=True,timeout=60)
    output.replace(folder/'listing-video.mp4');(folder/'captions.srt').write_text('\n'.join(captions))
    (folder/'video-checks.json').write_text(json.dumps({'duration_seconds':round(elapsed,2),'width':720,'height':1280,'audio':'Piper '+VOICE,'source':'listing photographs','scenes':timings},indent=2))
    # Keep the small reproducibility spec/timing report; release intermediate video space.
    for pattern in ['scene-*.mp4','scene-*.wav']:
        for p in work.glob(pattern): p.unlink()


if __name__=='__main__': worker(sys.argv[1])
