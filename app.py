"""Canvas Asistente v2: desktop, no OpenAI API, intentional supervised grading."""
import json
import threading
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import requests
from canvas_core import (Canvas, parse_assignment_url, export_assignment, read_package,
                         summary_counts, student_status, make_template, validate_grades,
                         safe_zero_candidates, register_grades)

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.configure(background='#fcf4f7')
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('.', background='#fcf4f7', foreground='#422b38', font=('Segoe UI', 10))
        style.configure('TButton', background='#b53468', foreground='white', padding=(12, 7))
        style.map('TButton', background=[('active', '#9c2958'), ('disabled', '#e8c7d6')])
        style.configure('TEntry', fieldbackground='white', padding=5)
        style.configure('TNotebook.Tab', padding=(14, 8))
        style.map('TNotebook.Tab', background=[('selected', '#f1d5e2')])
        style.configure('Treeview', background='white', fieldbackground='white', rowheight=28)
        style.configure('Treeview.Heading', background='#f1d5e2', foreground='#73344f')
        style.map('Treeview', background=[('selected', '#b53468')], foreground=[('selected', 'white')])
        self.title('Asistente Canvas — V2 · Descarga y registro')
        self.geometry('1030x760');self.minsize(800,600)
        self.manifest=None;self.grades=None;self.approved=[];self.zero_candidates=[];self.validated_link=None
        root=ttk.Frame(self,padding=14);root.pack(fill='both',expand=True)
        ttk.Label(root,text='Asistente Canvas V2',font=('Segoe UI',19,'bold')).pack(anchor='w')
        ttk.Label(root,text='Descarga de tareas · preparación de calificaciones · registro supervisado',foreground='#555').pack(anchor='w',pady=(0,12))
        info=ttk.Frame(root);info.pack(fill='x')
        ttk.Label(info,text='URL HTTPS de la tarea:').grid(row=0,column=0,sticky='w')
        self.url=ttk.Entry(info);self.url.grid(row=0,column=1,sticky='ew',padx=8,pady=4)
        ttk.Label(info,text='Token Canvas:').grid(row=1,column=0,sticky='w')
        self.token=ttk.Entry(info,show='●');self.token.grid(row=1,column=1,sticky='ew',padx=8,pady=4)
        info.columnconfigure(1,weight=1)
        ttk.Label(root,text='El token se usa solo en memoria. No se guarda en archivos ni se envía a OpenAI.',foreground='#555').pack(anchor='w')
        self.tabs=ttk.Notebook(root);self.tabs.pack(fill='both',expand=True,pady=(10,8))
        self.download_tab=ttk.Frame(self.tabs,padding=12);self.grade_tab=ttk.Frame(self.tabs,padding=12)
        self.tabs.add(self.download_tab,text='1 · Descargar y revisar');self.tabs.add(self.grade_tab,text='2 · Registrar evaluaciones')
        self._download_ui();self._grade_ui()
        ttk.Label(root,text='IMPORTANTE: el registro modifica notas reales en Canvas; requiere validación y confirmación explícita.',foreground='#8a4800').pack(anchor='w')
        self.logbox=tk.Text(root,height=7,state='disabled',wrap='word');self.logbox.pack(fill='x',pady=(8,0))
        self.controls=[]

    def _download_ui(self):
        bar=ttk.Frame(self.download_tab);bar.pack(fill='x')
        self.btn_download=ttk.Button(bar,text='Descargar entregas y generar ZIP',command=self.download);self.btn_download.pack(side='left',padx=(0,10))
        ttk.Button(bar,text='Abrir ZIP anterior',command=self.load_package).pack(side='left')
        self.summary=ttk.Label(self.download_tab,text='Selecciona una tarea para consultar sus entregas.',font=('Segoe UI',11))
        self.summary.pack(anchor='w',pady=12)
        cols=('id','name','status','note','files')
        self.tree=ttk.Treeview(self.download_tab,columns=cols,show='headings',height=15)
        for c,label,w in [('id','ID',80),('name','Estudiante',330),('status','Estado',175),('note','Nota previa',115),('files','Archivos',90)]:
            self.tree.heading(c,text=label);self.tree.column(c,width=w,anchor='w')
        self.tree.pack(fill='both',expand=True)
        ttk.Label(self.download_tab,text='Los registros sin archivo no siempre son estudiantes sin entrega; se muestran según el estado reportado por Canvas.',foreground='#555').pack(anchor='w',pady=6)
        ttk.Button(self.download_tab,text='Crear plantilla JSON para evaluar en ChatGPT',command=self.template).pack(anchor='w',pady=8)

    def _grade_ui(self):
        panel=ttk.Frame(self.grade_tab);panel.pack(fill='x')
        self.btn_json=ttk.Button(panel,text='Abrir JSON de calificaciones aprobadas',command=self.load_json)
        self.btn_json.pack(side='left')
        self.btn_check=ttk.Button(panel,text='Validar contra Canvas',command=self.validate_live)
        self.btn_check.pack(side='left',padx=10)
        self.include_zeros=tk.BooleanVar(value=False)
        ttk.Checkbutton(self.grade_tab,text='Incluir ceros solo para faltantes elegibles sin nota previa (requiere fecha vencida, sin prórrogas)',variable=self.include_zeros,command=self.invalidate_preview).pack(anchor='w',pady=10)
        self.preview=ttk.Treeview(self.grade_tab,columns=('id','name','score','action'),show='headings',height=13)
        for c,label,w in [('id','ID',90),('name','Estudiante',350),('score','Total',110),('action','Operación',160)]:
            self.preview.heading(c,text=label);self.preview.column(c,width=w)
        self.preview.pack(fill='both',expand=True)
        self.validation=ttk.Label(self.grade_tab,text='Abre el archivo JSON de evaluaciones para comenzar.',wraplength=850)
        self.validation.pack(anchor='w',pady=10)
        self.btn_register=ttk.Button(self.grade_tab,text='REGISTRAR EN CANVAS (requiere validación)',state='disabled',command=self.confirm_register)
        self.btn_register.pack(anchor='w',pady=5)

    def log(self,message):self.after(0,lambda m=message:self._append(m))
    def _append(self,message):
        self.logbox.config(state='normal');self.logbox.insert('end',message+'\n');self.logbox.see('end');self.logbox.config(state='disabled')
    def inputs(self):
        link=self.url.get().strip(); token=self.token.get().strip()
        parse_assignment_url(link)
        if not token:raise ValueError('Introduce tu token de Canvas.')
        return link,token
    def task(self,fn,on_ok=None):
        self.btn_download.config(state='disabled');self.btn_check.config(state='disabled');self.btn_register.config(state='disabled')
        def do():
            try:
                result=fn()
                if on_ok:self.after(0,lambda:on_ok(result))
            except Exception as e:
                self.log(f'ERROR: {e}')
                self.after(0,lambda msg=str(e):messagebox.showerror('Operación fallida',msg))
            finally:self.after(0,self.unlock)
        threading.Thread(target=do,daemon=True).start()
    def unlock(self):
        self.btn_download.config(state='normal');self.btn_check.config(state='normal')
    def display_manifest(self,manifest):
        self.manifest=manifest;self.invalidate_preview()
        for item in self.tree.get_children():self.tree.delete(item)
        for r in manifest['submissions']:
            self.tree.insert('',tk.END,values=(r['user_id'],r['student_name'],r.get('status') or student_status(r),
                                                '—' if r.get('score') is None else r['score'],len(r.get('attachments',[]))))
        c=summary_counts(manifest['submissions'])
        self.summary.config(text=f"{manifest.get('assignment_title','Tarea')} | Registros: {c['registros']} | Entregados: {c['entregados']} | Sin entrega: {c['sin_entrega']} | Con nota: {c['con_nota']} | Exonerados: {c['exonerados']}")
        if manifest.get('warnings'):messagebox.showwarning('Descarga incompleta',f"{len(manifest['warnings'])} advertencia(s). Revisa el ZIP antes de evaluar.")
    def download(self):
        try:link,token=self.inputs();_,course,aid=parse_assignment_url(link)
        except Exception as e:messagebox.showerror('Datos incompletos',str(e));return
        path=filedialog.asksaveasfilename(defaultextension='.zip',initialfile=f'canvas_curso_{course}_tarea_{aid}_v2.zip',filetypes=[('ZIP','*.zip')])
        if not path:return
        def work():return export_assignment(link,token,path,self.log)
        def done(result):
            manifest=read_package(path);self.display_manifest(manifest)
            self.log(f"Descarga completa: {result[0]} / Advertencias: {len(result[1])}")
            messagebox.showinfo('ZIP generado',f'Guardado en:\n{path}')
        self.task(work,done)
    def load_package(self):
        path=filedialog.askopenfilename(filetypes=[('Paquete Canvas','*.zip')])
        if not path:return
        try:
            m=read_package(path);self.display_manifest(m)
            self.url.delete(0,'end');self.url.insert(0,f"{m['canvas_base']}/courses/{m['course_id']}/assignments/{m['assignment_id']}")
            self.log(f'Paquete cargado: {path}')
        except Exception as e:messagebox.showerror('ZIP inválido',str(e))
    def template(self):
        if not self.manifest:messagebox.showwarning('Falta ZIP','Primero descarga o abre un paquete.');return
        try:tpl=make_template(self.manifest)
        except Exception as e:messagebox.showerror('Error',str(e));return
        path=filedialog.asksaveasfilename(defaultextension='.json',initialfile=f"plantilla_calificaciones_{self.manifest['assignment_id']}.json",filetypes=[('JSON','*.json')])
        if not path:return
        Path(path).write_text(json.dumps(tpl,ensure_ascii=False,indent=2),encoding='utf-8')
        messagebox.showinfo('Plantilla creada','La plantilla NO contiene notas inventadas.\nCompártela para completar las evaluaciones y revisa el resultado antes de importarlo.')
        self.log(f'Plantilla creada: {path}')
    def invalidate_preview(self):
        self.approved=[];self.zero_candidates=[];self.validated_link=None
        if hasattr(self,'btn_register'):self.btn_register.config(state='disabled')
        if hasattr(self,'validation'):self.validation.config(text='Se necesita una nueva validación contra Canvas antes de registrar.')
    def load_json(self):
        path=filedialog.askopenfilename(filetypes=[('Calificaciones aprobadas','*.json')])
        if not path:return
        try:
            data=json.loads(Path(path).read_text(encoding='utf-8'))
            if not isinstance(data,dict) or not isinstance(data.get('grades'),list):raise ValueError('No es un archivo de calificaciones válido.')
            self.grades=data;self.invalidate_preview()
            self._preview_rows(data['grades'],[])
            self.log(f"JSON seleccionado: {path} ({len(data['grades'])} filas)")
        except Exception as e:messagebox.showerror('JSON inválido',str(e))
    def _preview_rows(self,rows,zeros):
        for item in self.preview.get_children():self.preview.delete(item)
        for row in rows:
            self.preview.insert('',tk.END,values=(row.get('user_id'),row.get('student_name'),row.get('total'),'Registrar rúbrica'))
        for row in zeros:
            self.preview.insert('',tk.END,values=(row.get('user_id'),row.get('user',{}).get('name',''),0,'Cero por no entrega'))
    def validate_live(self):
        if not self.grades and not self.include_zeros.get():messagebox.showwarning('Falta JSON','Abre primero el JSON o selecciona ceros.');return
        try:link,token=self.inputs();base,course,aid=parse_assignment_url(link)
        except Exception as e:messagebox.showerror('Datos incompletos',str(e));return
        data=self.grades or {'schema_version':2,'canvas_base':base,'course_id':course,'assignment_id':aid,'grades':[]}
        def work():
            api=Canvas(base,token)
            try:
                a=api.get_assignment(course,aid);subs=api.get_submissions(course,aid)
                rows,errors=validate_grades(data,a,subs,base,course,aid)
                zeros,warnings=safe_zero_candidates(subs,a) if self.include_zeros.get() else ([],[])
                if not a.get('rubric'):errors.append('No hay rúbrica para asignar puntuación cero por criterio.')
                return rows,zeros,errors,warnings,a
            finally:api.close()
        def done(result):
            rows,zeros,errors,warnings,a=result
            self._preview_rows(rows,zeros)
            self.approved=rows if not errors else []
            self.zero_candidates=zeros if not errors else []
            self.validated_link=link if not errors and (rows or zeros) else None
            info=f"Tarea: {a.get('name')} | Evaluaciones válidas: {len(rows)} | Ceros propuestos: {len(zeros)} | Errores: {len(errors)}."
            self.validation.config(text=info+' '+ ('Revisa el registro antes de continuar.' if not errors else 'Registro BLOQUEADO por errores.'))
            for m in errors+warnings:self.log(('ERROR: ' if m in errors else 'AVISO: ')+m)
            if not errors and (rows or zeros):self.btn_register.config(state='normal')
            else:self.btn_register.config(state='disabled')
            self.log(info)
            if errors:messagebox.showerror('Validación fallida',f'{len(errors)} error(es). Revisa el panel Actividad.')
            else:messagebox.showinfo('Validación completada',info+'\nSi corresponde, confirma explícitamente el registro.')
        self.task(work,done)
    def confirm_register(self):
        if not self.approved and not self.zero_candidates:return
        count=len(self.approved)+len(self.zero_candidates)
        if not messagebox.askyesno('Modificar notas reales',f'Vas a modificar {count} calificaciones en Canvas.\n\nEvaluaciones: {len(self.approved)}\nCeros: {len(self.zero_candidates)}\n\n¿Has revisado todos los puntajes y comentarios?'):
            return
        dialog=tk.Toplevel(self);dialog.title('Confirmación final');dialog.geometry('480x170');dialog.transient(self);dialog.grab_set()
        ttk.Label(dialog,text='Para autorizar cambios reales, escribe REGISTRAR:',padding=14).pack(anchor='w')
        entry=ttk.Entry(dialog,width=28);entry.pack(padx=14,anchor='w');entry.focus_set()
        def authorize():
            if entry.get().strip()!='REGISTRAR':messagebox.showerror('Confirmación incorrecta','Escribe REGISTRAR exactamente.',parent=dialog);return
            dialog.destroy();self.write_to_canvas()
        ttk.Button(dialog,text='Confirmar escritura',command=authorize).pack(padx=14,pady=14,anchor='w')
    def write_to_canvas(self):
        try:link,token=self.inputs()
        except Exception as e:messagebox.showerror('Datos incompletos',str(e));return
        if link != self.validated_link:
            messagebox.showerror('Enlace modificado','La URL cambió después de validar. Valida nuevamente antes de registrar.');self.invalidate_preview();return
        rows=list(self.approved);zeros=list(self.zero_candidates)
        self.btn_register.config(state='disabled')
        def work():return register_grades(link,token,rows,zeros,self.log)
        def done(results):
            path=filedialog.asksaveasfilename(defaultextension='.json',initialfile=f'reporte_canvas_{datetime.now():%Y%m%d_%H%M%S}.json',filetypes=[('JSON','*.json')])
            if path:Path(path).write_text(json.dumps({'results':results},ensure_ascii=False,indent=2),encoding='utf-8')
            by={x:sum(1 for r in results if r['status']==x) for x in ('CONFIRMADO','REVISAR','OMITIDO','ERROR')}
            self.invalidate_preview()
            messagebox.showinfo('Registro terminado',f"Confirmados: {by['CONFIRMADO']}\nRevisar: {by['REVISAR']}\nOmitidos: {by['OMITIDO']}\nErrores: {by['ERROR']}\n\nVerifica SpeedGrader y guarda el reporte.")
        self.task(work,done)

if __name__=='__main__':
    App().mainloop()
