import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
import shutil
from collections import defaultdict
import threading

# ===== Config: carpetas y extensiones =====
DESTINOS = {
    "Imágenes": {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".svg", ".heic"},
    "PDFs": {".pdf"},
    "Vídeos": {".mp4", ".mov", ".avi", ".mkv", ".webm", ".wmv"},
    "Documentos Word": {".doc", ".docx", ".odt"},
    "Excel": {".xls", ".xlsx", ".xlsm", ".xlsb", ".xltx", ".ods", ".csv"},
    "Texto": {".txt", ".md", ".rtf"},
}
CARPETA_OTROS = "Otros"
EXT_A_CARPETA = {ext: carpeta for carpeta, exts in DESTINOS.items() for ext in exts}

# ===== Utilidades =====
def ruta_unica(dest: Path) -> Path:
    """Si dest existe, devuelve 'nombre (n).ext' libre."""
    if not dest.exists():
        return dest
    i = 1
    while True:
        candidato = dest.with_name(f"{dest.stem} ({i}){dest.suffix}")
        if not candidato.exists():
            return candidato
        i += 1

def listar_archivos(base: Path, recursivo: bool):
    it = base.rglob("*") if recursivo else base.iterdir()
    destinos = set(DESTINOS.keys()) | {CARPETA_OTROS}
    for p in it:
        if not p.is_file():
            continue
        if p.name.startswith("~$"):  # temporales de Office
            continue
        if p.parent.name in destinos:  # ya está clasificado
            continue
        yield p

def organizar(ruta: Path, recursivo: bool, dry_run: bool, on_log, on_progress):
    """Core de organización. on_log(str), on_progress(curr, total)"""
    ruta = ruta.expanduser().resolve()
    if not ruta.is_dir():
        raise ValueError(f"Ruta no válida: {ruta}")

    # Crear carpetas destino
    for carpeta in list(DESTINOS.keys()) + [CARPETA_OTROS]:
        (ruta / carpeta).mkdir(exist_ok=True)

    archivos = list(listar_archivos(ruta, recursivo))
    total = len(archivos)
    on_progress(0, total)

    movidos = defaultdict(int)
    errores = 0

    for i, p in enumerate(archivos, start=1):
        ext = p.suffix.casefold()
        carpeta = EXT_A_CARPETA.get(ext, CARPETA_OTROS)
        destino_dir = ruta / carpeta
        destino = ruta_unica(destino_dir / p.name)

        try:
            on_log(f"{p.name}  →  {carpeta}/")
            if not dry_run:
                shutil.move(str(p), str(destino))
            movidos[carpeta] += 1
        except Exception as ex:
            errores += 1
            on_log(f"   ⚠️ Error moviendo '{p.name}': {ex}")

        on_progress(i, total)

    return movidos, errores

# ===== GUI =====
class OrganizadorGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Organizador de archivos por tipo")
        self.root.minsize(720, 480)

        self.path_var = tk.StringVar(value=r"C:/Users/agran/OneDrive/Escritorio/auto_python")
        self.recursive_var = tk.BooleanVar(value=False)
        self.dry_run_var = tk.BooleanVar(value=False)

        self._build_ui()

    def _build_ui(self):
        frm_top = ttk.Frame(self.root, padding=12)
        frm_top.pack(fill="x")

        ttk.Label(frm_top, text="Carpeta:").pack(side="left")
        self.entry_path = ttk.Entry(frm_top, textvariable=self.path_var)
        self.entry_path.pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(frm_top, text="Buscar…", command=self._browse).pack(side="left")

        frm_opts = ttk.Frame(self.root, padding=(12, 0))
        frm_opts.pack(fill="x")
        ttk.Checkbutton(frm_opts, text="Recursivo (incluir subcarpetas)", variable=self.recursive_var).pack(side="left")
        ttk.Checkbutton(frm_opts, text="Simular (no mover)", variable=self.dry_run_var).pack(side="left", padx=(12, 0))

        # Barra de progreso
        frm_prog = ttk.Frame(self.root, padding=(12, 8))
        frm_prog.pack(fill="x")
        self.progress = ttk.Progressbar(frm_prog, mode="determinate")
        self.progress.pack(fill="x", expand=True)
        self.lbl_status = ttk.Label(frm_prog, text="Listo.")
        self.lbl_status.pack(anchor="w", pady=(4, 0))

        # Log
        frm_log = ttk.Frame(self.root, padding=12)
        frm_log.pack(fill="both", expand=True)
        self.txt_log = tk.Text(frm_log, height=12, wrap="none")
        yscroll = ttk.Scrollbar(frm_log, orient="vertical", command=self.txt_log.yview)
        self.txt_log.configure(yscrollcommand=yscroll.set)
        self.txt_log.pack(side="left", fill="both", expand=True)
        yscroll.pack(side="right", fill="y")

        # Botones
        frm_btns = ttk.Frame(self.root, padding=12)
        frm_btns.pack(fill="x")
        self.btn_run = ttk.Button(frm_btns, text="Organizar", command=self._run)
        self.btn_run.pack(side="left")
        ttk.Button(frm_btns, text="Salir", command=self.root.quit).pack(side="right")

    # ---- helpers UI ----
    def _browse(self):
        d = filedialog.askdirectory(initialdir=self.path_var.get() or None)
        if d:
            self.path_var.set(d)

    def _log(self, msg: str):
        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", msg + "\n")
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")

    def _set_progress(self, curr: int, total: int):
        self.progress["maximum"] = max(1, total)
        self.progress["value"] = curr
        if total == 0:
            self.lbl_status.configure(text="No hay archivos que organizar.")
        else:
            self.lbl_status.configure(text=f"Procesado {curr}/{total}")

    def _run(self):
        ruta = Path(self.path_var.get())
        rec = self.recursive_var.get()
        dry = self.dry_run_var.get()

        if not ruta.exists():
            messagebox.showerror("Error", "La ruta no existe.")
            return

        # Reset UI
        self.txt_log.configure(state="normal")
        self.txt_log.delete("1.0", "end")
        self.txt_log.configure(state="disabled")
        self._set_progress(0, 1)
        self.btn_run.configure(state="disabled")
        self.lbl_status.configure(text="Trabajando…")

        # Lanzar en hilo para no congelar la ventana
        def worker():
            try:
                movidos, errores = organizar(
                    ruta, rec, dry,
                    on_log=lambda m: self.root.after(0, self._log, m),
                    on_progress=lambda c, t: self.root.after(0, self._set_progress, c, t),
                )
                resumen = "\nResumen:\n" + "\n".join(f"  {k}: {v}" for k, v in sorted(movidos.items()))
                if errores:
                    resumen += f"\n  Errores: {errores}"
                self.root.after(0, self._log, resumen)
                self.root.after(0, self.lbl_status.configure, {"text": "Completado."})
                self.root.after(0, self.btn_run.configure, {"state": "normal"})
                if not sum(movidos.values()):
                    self.root.after(0, messagebox.showinfo, "Organizador", "No había nada que mover.")
                else:
                    modo = "Simulación" if dry else "Hecho"
                    self.root.after(0, messagebox.showinfo, "Organizador", f"{modo}.\n{resumen}")
            except Exception as ex:
                self.root.after(0, self.btn_run.configure, {"state": "normal"})
                self.root.after(0, self.lbl_status.configure, {"text": "Error"})
                self.root.after(0, messagebox.showerror, "Error", str(ex))

        threading.Thread(target=worker, daemon=True).start()

if __name__ == "__main__":
    root = tk.Tk()
    # Ajuste visual leve (Windows 10/11)
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    OrganizadorGUI(root)
    root.mainloop()