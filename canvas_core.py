"""Canvas client and local evaluation package. No OpenAI API required."""
import json
import re
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime, timezone
import requests

ASSIGNMENT_URL = re.compile(r"^/courses/(\d+)/assignments/(\d+)(?:/.*)?$")
PRIVATE_ASSIGNMENT_KEYS = {'secure_params', 'integration_data', 'lti_context_id', 'sis_assignment_id', 'integration_id'}

def parse_assignment_url(value):
    p = urlparse(value.strip())
    if p.scheme != 'https' or not p.hostname or p.username or p.password or p.port or p.fragment:
        raise ValueError('Introduce la URL HTTPS de una tarea de Canvas, sin credenciales ni puerto.')
    match = ASSIGNMENT_URL.fullmatch(p.path.rstrip('/'))
    if not match:
        raise ValueError('El enlace debe contener /courses/ID/assignments/ID')
    return f'https://{p.hostname}', int(match.group(1)), int(match.group(2))

def safe_name(v):
    return (re.sub(r'[^\w.\- ]+', '_', str(v), flags=re.UNICODE).strip(' .') or 'archivo')[:100]

def number(v):
    if isinstance(v, bool) or v is None:
        raise ValueError('Puntuación numérica obligatoria.')
    n = float(v)
    if not (float('-inf') < n < float('inf')):
        raise ValueError('Puntuación no finita.')
    return n

def clean_assignment(a):
    return {k: v for k, v in a.items() if k not in PRIVATE_ASSIGNMENT_KEYS and not any(s in k for s in ('token', 'secret'))}

class Canvas:
    def __init__(self, base, token):
        self.base = base
        self.session = requests.Session()
        self.session.headers.update({'Authorization': f'Bearer {token}', 'Accept': 'application/json'})
    def request(self, method, path, **kw):
        url = f"{self.base}/api/v1/{path.lstrip('/')}"
        response = self.session.request(method, url, timeout=55, allow_redirects=False, **kw)
        response.raise_for_status()
        return response.json() if response.content else {}
    def get(self, path, params=None):
        return self.request('GET', path, params=params)
    def put(self, path, data):
        return self.request('PUT', path, data=data)
    def pages(self, path, params=None):
        url = f"{self.base}/api/v1/{path.lstrip('/')}"
        result = []
        for _ in range(300):
            r = self.session.get(url, params=params, timeout=55, allow_redirects=False)
            r.raise_for_status()
            data = r.json()
            if not isinstance(data, list):
                raise ValueError('Canvas no devolvió una lista.')
            result.extend(data)
            nxt = r.links.get('next', {}).get('url')
            if nxt and urlparse(nxt).hostname != urlparse(self.base).hostname:
                raise ValueError('Paginación a un dominio distinto de Canvas.')
            url, params = nxt, None
            if not url: return result
        raise RuntimeError('Límite de paginación alcanzado.')
    def get_assignment(self, course, assignment):
        return self.get(f'courses/{course}/assignments/{assignment}')
    def get_submissions(self, course, assignment):
        return self.pages(f'courses/{course}/assignments/{assignment}/submissions',
                          {'per_page':100,'include[]':['user','group','rubric_assessment','submission_comments']})
    def get_submission(self, course, assignment, uid):
        return self.get(f'courses/{course}/assignments/{assignment}/submissions/{uid}',
                        {'include[]':['rubric_assessment','submission_comments']})
    def download(self, file_id, dest):
        info = self.get(f'files/{file_id}')
        url = info.get('url')
        if not url or urlparse(url).scheme != 'https':
            raise ValueError('Canvas no proporcionó enlace HTTPS para descargar.')
        # Authorization is never sent to the signed file URL.
        with requests.get(url, timeout=90, stream=True) as r:
            r.raise_for_status()
            with open(dest, 'wb') as out:
                for chunk in r.iter_content(65536):
                    if chunk: out.write(chunk)
    def close(self):
        self.session.close()

def student_status(s):
    if s.get('excused'): return 'Exonerado'
    if s.get('submitted_at') or s.get('workflow_state') in ('submitted','graded') and s.get('submission_type') not in (None,'none'):
        return 'Entregado'
    if s.get('score') is not None: return 'Sin entrega / nota previa'
    return 'Sin entrega'

def summary_counts(subs):
    result = {'registros':len(subs),'entregados':0,'sin_entrega':0,'con_nota':0,'exonerados':0}
    for s in subs:
        if s.get('excused'): result['exonerados']+=1
        elif student_status(s)=='Entregado': result['entregados']+=1
        else: result['sin_entrega']+=1
        if s.get('score') is not None: result['con_nota']+=1
    return result

def rubric(a):
    return a.get('rubric') or []

def export_assignment(link, token, destination, log):
    base, course, aid = parse_assignment_url(link)
    api=Canvas(base,token)
    try:
        log('Consultando tarea, rúbrica y estudiantes...')
        a=api.get_assignment(course,aid)
        subs=api.get_submissions(course,aid)
        log(f"Registros {len(subs)}. Preparando archivos...")
        manifest={'schema_version':2,'canvas_base':base,'course_id':course,'assignment_id':aid,
                  'assignment_title':a.get('name'),'max_points':a.get('points_possible'),
                  'rubric':rubric(a),'rubric_settings':a.get('rubric_settings'),
                  'submissions':[],'warnings':[]}
        out=Path(destination)
        out.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
            z.writestr('tarea_canvas.json',json.dumps(clean_assignment(a),ensure_ascii=False,indent=2))
            for index,s in enumerate(subs,1):
                uid=s.get('user_id')
                person=(s.get('user') or {}).get('name') or f'Estudiante_{uid}'
                folder=f'entregas/{uid}_{safe_name(person)}/'
                row={key:s.get(key) for key in ('user_id','submitted_at','workflow_state','missing','late','excused','score','grade','submission_type','group')}
                row.update(student_name=person,attachments=[],status=student_status(s))
                if s.get('body'): z.writestr(folder+'texto_entrega.html',s['body'])
                if s.get('url'): z.writestr(folder+'enlace_entrega.txt',s['url'])
                for att in s.get('attachments') or []:
                    fid=att.get('id')
                    filename=f"{fid}_{safe_name(att.get('filename') or 'archivo')}"
                    target=folder+filename
                    try:
                        local=Path(tmp)/filename
                        api.download(fid,local)
                        z.write(local,target)
                        row['attachments'].append({'file_id':fid,'name':target,'downloaded':True})
                        local.unlink(missing_ok=True)
                    except Exception as e:
                        msg=f"No se pudo descargar archivo {fid}, estudiante {uid}: {e}"
                        manifest['warnings'].append(msg);log(msg)
                        row['attachments'].append({'file_id':fid,'name':filename,'downloaded':False})
                manifest['submissions'].append(row)
                if index%5==0:log(f'Procesados {index} de {len(subs)} registros.')
            z.writestr('resumen_entregas.json',json.dumps(manifest,ensure_ascii=False,indent=2))
            z.writestr('LEEME.txt','Datos académicos confidenciales. No compartir tokens.\nLa evaluación humana debe aprobarse antes del registro.\n')
        counts=summary_counts(subs)
        log(f"ZIP preparado: {out}")
        return counts,manifest['warnings']
    finally:api.close()

def read_package(path):
    with zipfile.ZipFile(path) as z:
        data=json.loads(z.read('resumen_entregas.json'))
    if 'course_id' not in data or 'assignment_id' not in data or 'submissions' not in data:
        raise ValueError('ZIP sin manifiesto de Canvas válido.')
    return data

def make_template(manifest):
    """Template includes only submitted, ungraded students. Never invent grades."""
    criteria=manifest.get('rubric') or []
    if not criteria:
        raise ValueError('La tarea no tiene rúbrica; no es posible crear plantilla de criterios.')
    rows=[]
    for s in manifest['submissions']:
        if student_status(s)!='Entregado' or s.get('score') is not None:continue
        rows.append({'user_id':s['user_id'],'student_name':s['student_name'],'total':None,
                     'comment':'','criteria':[
                         {'criterion_id':r['id'],'points':None,'rating_id':None,'comment':''}
                         for r in criteria]})
    return {'schema_version':2,'canvas_base':manifest['canvas_base'],
            'course_id':manifest['course_id'],'assignment_id':manifest['assignment_id'],
            'assignment_title':manifest.get('assignment_title'),'grades':rows}

def validate_grades(data,assignment,submissions,expected_base,course,aid):
    """Strict offline checks; missing rows cannot be graded by JSON."""
    errors=[];prepared=[]
    if data.get('schema_version')!=2:errors.append('schema_version debe ser 2.')
    if data.get('canvas_base')!=expected_base or str(data.get('course_id'))!=str(course) or str(data.get('assignment_id'))!=str(aid):
        errors.append('El JSON no corresponde a la tarea y servidor indicados.')
    if not assignment.get('rubric'):errors.append('La tarea no tiene rúbrica asociada.')
    if assignment.get('anonymous_grading') or assignment.get('moderated_grading'):
        errors.append('La tarea tiene calificación anónima o moderada; registro deshabilitado en V2.')
    if assignment.get('group_category_id') and not assignment.get('grade_group_students_individually'):
        errors.append('La tarea tiene calificación grupal compartida; registro automático deshabilitado en V2.')
    if assignment.get('grading_type') not in ('points',None):errors.append('La tarea no está configurada con calificación por puntos.')
    by_student={str(s.get('user_id')):s for s in submissions}
    rub=assignment.get('rubric') or []
    by_criterion={str(x['id']):x for x in rub}
    expected=set(by_criterion)
    if not isinstance(data.get('grades'),list):return [],errors+['grades debe ser una lista.']
    seen=set()
    for ix,row in enumerate(data['grades'],1):
        uid=str(row.get('user_id'))
        heading=f'Fila {ix}, usuario {uid}: '
        if uid in seen: errors.append(heading+'ID duplicado.');continue
        seen.add(uid)
        sub=by_student.get(uid)
        if not sub:errors.append(heading+'No pertenece a la tarea.');continue
        if sub.get('excused') or student_status(sub)!='Entregado':errors.append(heading+'Sin entrega válida o exonerado.');continue
        if sub.get('score') is not None:errors.append(heading+'Ya tiene una calificación; no se sobrescribe.');continue
        if not isinstance(row.get('criteria'),list):errors.append(heading+'criteria debe ser una lista.');continue
        ids=[str(c.get('criterion_id')) for c in row['criteria']]
        if len(ids)!=len(set(ids)) or set(ids)!=expected:
            errors.append(heading+'Los criterios no coinciden exactamente con la rúbrica actual.');continue
        subtotal=0.;valid=True
        for c in row['criteria']:
            criterion=by_criterion[str(c['criterion_id'])]
            try:pts=number(c.get('points'))
            except (ValueError,TypeError):errors.append(heading+f"Puntos inválidos en criterio {c['criterion_id']}.");valid=False;continue
            maxpts=number(criterion['points'])
            if pts < -0.00001 or pts > maxpts+0.00001:
                errors.append(heading+f"Puntos fuera del rango 0–{maxpts}.");valid=False
            subtotal+=pts
            rating=c.get('rating_id')
            if rating is not None and str(rating) not in {str(r['id']) for r in criterion.get('ratings',[])}:
                errors.append(heading+'rating_id inexistente en el criterio.');valid=False
            if len(str(c.get('comment') or ''))>4000:errors.append(heading+'Comentario de criterio demasiado largo.');valid=False
        try:total=number(row.get('total'))
        except (ValueError,TypeError):errors.append(heading+'Total numérico obligatorio.');continue
        if abs(subtotal-total)>0.011:errors.append(heading+f'La suma de criterios ({subtotal:.2f}) difiere del total ({total:.2f}).');valid=False
        if abs(total)>0.00001 and not (0<=total<=number(assignment.get('points_possible'))+0.00001):
            errors.append(heading+'Total fuera del máximo de la tarea.');valid=False
        if not str(row.get('comment') or '').strip():errors.append(heading+'Comentario individual obligatorio.');valid=False
        if len(str(row.get('comment') or ''))>7000:errors.append(heading+'Comentario demasiado largo.');valid=False
        if valid: prepared.append(row)
    return prepared,errors

def safe_zero_candidates(submissions,assignment):
    """Conservative: do not zero any submission with prior score, extension or unexpired due date."""
    if assignment.get('group_category_id') or assignment.get('anonymous_grading') or assignment.get('moderated_grading'):
        return [],['Tarea grupal, anónima o moderada: ceros automáticos deshabilitados.']
    if assignment.get('has_overrides'):
        return [],['Hay fechas diferenciadas: ceros automáticos deshabilitados (revisar prórrogas en Canvas).']
    due=assignment.get('due_at')
    if not due:return [],['La tarea no tiene vencimiento general: ceros automáticos deshabilitados.']
    try: due_dt=datetime.fromisoformat(due.replace('Z','+00:00'))
    except Exception:return [],['La fecha límite no se puede interpretar.']
    if due_dt > datetime.now(timezone.utc):return [],['La fecha límite aún no ha transcurrido.']
    candidates=[]
    for s in submissions:
        if (s.get('score') is None and not s.get('excused') and not s.get('submitted_at')
            and s.get('workflow_state') in ('unsubmitted','pending_review',None)
            and s.get('submission_type') in (None,'none')):
            candidates.append(s)
    return candidates,[]

def build_form(row, rubric_rows, zero=False):
    form={}
    criteria = ({str(x['criterion_id']):x for x in row.get('criteria',[])} if not zero else {})
    for cr in rubric_rows:
        cid=str(cr['id']);x=criteria.get(cid,{})
        pts=0 if zero else number(x['points'])
        form[f'rubric_assessment[{cid}][points]']=str(pts)
        rid = x.get('rating_id')
        if zero:
            zero_ratings=[r for r in cr.get('ratings',[]) if abs(float(r.get('points',-99)))<0.00001]
            rid=zero_ratings[0]['id'] if zero_ratings else None
        if rid is not None:form[f'rubric_assessment[{cid}][rating_id]']=str(rid)
        comment=str(x.get('comment') or '')
        if comment:form[f'rubric_assessment[{cid}][comments]']=comment
    form['submission[posted_grade]']=str(0 if zero else number(row['total']))
    comment='Sin entrega registrada al cierre de la actividad.' if zero else str(row['comment'])
    form['comment[text_comment]']=comment
    form['comment[group_comment]']='false'
    return form,comment

def verify_submission(sub, row, rubric_rows, zero, expected_comment):
    reasons=[]
    expected=0 if zero else float(row['total'])
    if sub.get('score') is None or abs(float(sub['score'])-expected)>0.02:
        reasons.append(f'Nota esperada {expected:.2f}, recibida {sub.get("score")}')
    assessment=sub.get('rubric_assessment')
    if not isinstance(assessment,dict):
        reasons.append('Canvas no devolvió rubric_assessment para verificar criterios.');return reasons
    byid={} if zero else {str(c['criterion_id']):c for c in row['criteria']}
    for cr in rubric_rows:
        cid=str(cr['id']);got=assessment.get(cid)
        if not isinstance(got,dict):reasons.append(f'No se recuperó criterio {cid}.');continue
        expected_points=0 if zero else float(byid[cid]['points'])
        if got.get('points') is None or abs(float(got['points'])-expected_points)>0.02:
            reasons.append(f'Criterio {cid}: puntos no coinciden.')
        requested= None if zero else byid[cid].get('rating_id')
        if zero:
            rr=[r for r in cr.get('ratings',[]) if abs(float(r.get('points',-99)))<0.00001]
            requested=rr[0]['id'] if rr else None
        if requested is not None and str(got.get('rating_id'))!=str(requested):
            reasons.append(f'Criterio {cid}: nivel no confirmado.')
    comments=sub.get('submission_comments')
    if isinstance(comments,list) and not any(str(c.get('comment') or '').strip()==expected_comment for c in comments):
        reasons.append('Comentario no confirmado en comentarios recientes.')
    return reasons

def register_grades(link,token,rows,zero_rows,log):
    base,course,aid=parse_assignment_url(link); api=Canvas(base,token)
    results=[]
    try:
        a=api.get_assignment(course,aid)
        if zero_rows:
            latest=api.get_submissions(course,aid)
            allowed={str(x['user_id']) for x in safe_zero_candidates(latest,a)[0]}
            zero_rows=[x for x in zero_rows if str(x['user_id']) in allowed]
        for row,zero in [(x,False) for x in rows]+[(x,True) for x in zero_rows]:
            uid=row['user_id'];item={'user_id':uid,'student_name':row.get('student_name'),'mode':'CERO' if zero else 'EVALUACION'}
            try:
                live=api.get_submission(course,aid,uid)
                if live.get('score') is not None or live.get('excused') or (zero and live.get('submitted_at')) or (not zero and student_status(live)!='Entregado'):
                    item.update(status='OMITIDO',detail='Estado cambió antes del registro; consultar Canvas.');results.append(item);continue
                form,comment=build_form(row,rubric(a),zero)
                api.put(f'courses/{course}/assignments/{aid}/submissions/{uid}',form)
                saved=api.get_submission(course,aid,uid)
                problems=verify_submission(saved,row,rubric(a),zero,comment)
                item.update(status='CONFIRMADO' if not problems else 'REVISAR',detail='; '.join(problems))
            except Exception as e:
                item.update(status='ERROR',detail=str(e))
            results.append(item)
            log(f"{uid}: {item['status']} {item.get('detail','')}")
        return results
    finally:api.close()
