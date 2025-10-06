# GUI con popup de bienvenida
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, font as tkfont
from pathlib import Path
import shutil
from collections import defaultdict
import threading
import json
import os
from datetime import datetime

# Config persistente (APPDATA)
APP_DIR = Path(os.getenv('APPDATA', Path.home())) / "OrganizadorArchivos"
CONFIG_PATH = APP_DIR / "config.json"

def load_config():
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def save_config(cfg: dict):
    APP_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

# Config: carpetas y extensiones
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

# Subcarpetas por fecha para ciertas categorías
DATE_SUBFOLDERS = {
    "Excel": "%Y/%m",
    "Documentos Word": "%Y/%m",
}

# Utilidades
def ruta_unica(dest: Path) -> Path:
    if not dest.exists():
        return dest
    i = 1
    while True:
        candidato = dest.with_name(f"{dest.stem} ({i}){dest.suffix}")
        if not candidato.exists():
            return candidato
        i += 1

def _esta_dentro_de_destino(base: Path, p: Path) -> bool:

    try:
        rel = p.relative_to(base)
    except Exception:
        return False
    if not rel.parts:
        return False
    primer_nivel = rel.parts[0]
    destinos = set(DESTINOS.keys()) | {CARPETA_OTROS}
    return primer_nivel in destinos

def listar_archivos(base: Path, recursivo: bool):
    it = base.rglob("*") if recursivo else base.iterdir()
    for p in it:
        if not p.is_file():
            continue
        # Ignorar temporales de Office
        if p.name.startswith("~$"):
            continue
        if _esta_dentro_de_destino(base, p):
            continue
        yield p

def _directorio_destino(base: Path, p: Path, carpeta: str) -> Path:
    dest = base / carpeta
    if carpeta in DATE_SUBFOLDERS:
        # Usamos la fecha de modificación del archivo
        dt = datetime.fromtimestamp(p.stat().st_mtime)
        sub = dt.strftime(DATE_SUBFOLDERS[carpeta])
        dest = dest / Path(*sub.split("/"))
    return dest

def organizar(ruta: Path, recursivo: bool, dry_run: bool, on_log, on_progress):
    ruta = ruta.expanduser().resolve()
    if not ruta.is_dir():
        raise ValueError(f"Ruta no válida: {ruta}")

    # Crear carpetas destino top-level
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

        # Directorio final (incluye subcarpetas por fecha si procede)
        destino_dir = _directorio_destino(ruta, p, carpeta)
        destino_dir.mkdir(parents=True, exist_ok=True)

        destino = ruta_unica(destino_dir / p.name)

        try:
            subruta_rel = destino_dir.relative_to(ruta).as_posix() + "/"
        except Exception:
            subruta_rel = f"{carpeta}/"

        try:
            on_log(f"{p.name}  →  {subruta_rel}")
            if not dry_run:
                shutil.move(str(p), str(destino))
            movidos[carpeta] += 1
        except Exception as ex:
            errores += 1
            on_log(f"   ⚠️ Error moviendo '{p.name}': {ex}")

        on_progress(i, total)

    return movidos, errores

# GUI
class OrganizadorGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Organizador de archivos por tipo")
        self.root.minsize(900, 560)
        self.root.geometry("1000x650")

        self.path_var = tk.StringVar(value=r"C:/Users/agran/OneDrive/Escritorio/auto_python")
        self.recursive_var = tk.BooleanVar(value=False)
        self.dry_run_var = tk.BooleanVar(value=False)

        self._build_ui()

        # Config persistente y bienvenida
        self.config = load_config()
        self._maybe_show_welcome()

    def _build_ui(self):
        frm_top = ttk.Frame(self.root, padding=14)
        frm_top.pack(fill="x")

        ttk.Label(frm_top, text="Carpeta:").pack(side="left")
        self.entry_path = ttk.Entry(frm_top, textvariable=self.path_var)
        self.entry_path.pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(frm_top, text="Buscar…", command=self._browse).pack(side="left")

        frm_opts = ttk.Frame(self.root, padding=(14, 0))
        frm_opts.pack(fill="x")
        ttk.Checkbutton(frm_opts, text="Recursivo (incluir subcarpetas)", variable=self.recursive_var).pack(side="left")
        ttk.Checkbutton(frm_opts, text="Simular (no mover)", variable=self.dry_run_var).pack(side="left", padx=(14, 0))

        # Barra de progreso
        frm_prog = ttk.Frame(self.root, padding=(14, 10))
        frm_prog.pack(fill="x")
        self.progress = ttk.Progressbar(frm_prog, mode="determinate")
        self.progress.pack(fill="x", expand=True)
        self.lbl_status = ttk.Label(frm_prog, text="Listo.")
        self.lbl_status.pack(anchor="w", pady=(6, 0))

        # Log
        frm_log = ttk.Frame(self.root, padding=14)
        frm_log.pack(fill="both", expand=True)
        self.txt_log = tk.Text(frm_log, height=16, wrap="none")
        yscroll = tk.Scrollbar(frm_log, orient="vertical", command=self.txt_log.yview, width=18)
        self.txt_log.configure(yscrollcommand=yscroll.set)
        self.txt_log.pack(side="left", fill="both", expand=True)
        yscroll.pack(side="right", fill="y")

        # Botones
        frm_btns = ttk.Frame(self.root, padding=14)
        frm_btns.pack(fill="x")
        self.btn_run = ttk.Button(frm_btns, text="Organizar", command=self._run)
        self.btn_run.pack(side="left")
        ttk.Button(frm_btns, text="Salir", command=self.root.quit).pack(side="right")
        ttk.Button(frm_btns, text="Acerca de", command=self._acerca_de).pack(side="right", padx=(0, 8))
        ttk.Button(frm_btns, text="Ayuda", command=self._show_welcome_modal).pack(side="right", padx=(0, 8))

    # helpers UI
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

    # helpers de centrado
    def _center_child(self, win: tk.Toplevel):
        try:
            win.update_idletasks()
            self.root.update_idletasks()
            pw, ph = self.root.winfo_width(), self.root.winfo_height()
            wx, wh = win.winfo_width(), win.winfo_height()
            x = self.root.winfo_rootx() + max(0, (pw - wx) // 2)
            y = self.root.winfo_rooty() + max(0, (ph - wh) // 2)
            win.geometry(f"+{x}+{y}")
        except Exception:
            pass

    # Bienvenida / Ayuda
    def _maybe_show_welcome(self):
        # Muéstralo solo si no se ha marcado "no volver a mostrar"
        if not self.config.get("suppress_welcome_v2", False):
            self._show_welcome_modal()

    def _show_welcome_modal(self):
        win = tk.Toplevel(self.root)
        win.title("Cómo funciona")
        win.transient(self.root)
        win.grab_set()  # modal
        win.resizable(False, False)

        frm = ttk.Frame(win, padding=18)
        frm.pack(fill="both", expand=True)

        texto = (
            "¿Qué hace esta app?\n"
            "• Crea carpetas: Imágenes, PDFs, Vídeos, Documentos Word, Excel, Texto y Otros.\n"
            "• Mueve tus archivos a la carpeta según su extensión.\n"
            "• Evita tocar lo que ya esté dentro de esas carpetas.\n"
            "• Si el nombre existe, renombra a (1), (2), … para evitar colisiones.\n"
            "• En 'Excel' y 'Texto' además organiza en subcarpetas por fecha (AAAA/MM) según la fecha de modificación.\n\n"
            "Opciones:\n"
            "• Recursivo: incluye subcarpetas.\n"
            "• Simular: no mueve nada, solo muestra el plan.\n\n"
            "Consejo: prueba primero con Simular (por si acaso 😉)."
        )

        ttk.Label(frm, text=texto, justify="left", wraplength=640).pack(anchor="w")

        self.no_mostrar_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            frm,
            text="No volver a mostrar al iniciar",
            variable=self.no_mostrar_var
        ).pack(anchor="w", pady=(10, 0))

        btns = ttk.Frame(frm)
        btns.pack(fill="x", pady=(12, 0))
        ttk.Button(btns, text="Entendido", command=lambda: self._cerrar_bienvenida(win)).pack(side="right")

        self._center_child(win)
        self.root.after(0, lambda: self._center_child(win))

    def _cerrar_bienvenida(self, win):
        if self.no_mostrar_var.get():
            self.config["suppress_welcome_v2"] = True
            save_config(self.config)
        win.destroy()

    def _acerca_de(self):
        import tkinter as tk
        from tkinter import ttk
        import webbrowser

        url = "https://ko-fi.com/alvarogr87"

        win = tk.Toplevel(self.root)
        win.title("Acerca de")
        win.transient(self.root)
        win.grab_set()  # modal
        win.resizable(False, False)

        frm = ttk.Frame(win, padding=18)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="Organizador de archivos — versión básica",
                  font=("Segoe UI", 12, "bold")).pack(anchor="w")
        ttk.Label(frm, text="Desarrollado por Álvaro Granados Ruiz.").pack(anchor="w", pady=(4, 0))
        ttk.Label(frm, text="Sin anuncios. No se venderá. Solo utilidad y cariño 😉",
                  wraplength=520, justify="left").pack(anchor="w", pady=(0, 8))

        ttk.Separator(frm).pack(fill="x", pady=8)

        ttk.Label(frm, text="¿Te ha ahorrado tiempo? Puedes invitarme a un café:").pack(anchor="w")

        link = ttk.Label(frm, text=url, foreground="blue", cursor="hand2")
        link.pack(anchor="w", pady=(2, 8))
        link.bind("<Button-1>", lambda e: webbrowser.open(url))

        btns = ttk.Frame(frm)
        btns.pack(fill="x")
        ttk.Button(btns, text="☕ Invitar en Ko-fi", command=lambda: webbrowser.open(url)).pack(side="right")
        ttk.Button(btns, text="Cerrar", command=win.destroy).pack(side="right", padx=(0, 8))

        try:
            self._center_child(win)
            self.root.after(0, lambda: self._center_child(win))
        except Exception:
            win.update_idletasks()
            x = self.root.winfo_rootx() + (self.root.winfo_width() - win.winfo_width()) // 2
            y = self.root.winfo_rooty() + (self.root.winfo_height() - win.winfo_height()) // 2
            win.geometry(f"+{x}+{y}")

if __name__ == "__main__":
    root = tk.Tk()

    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    try:
        root.tk.call('tk', 'scaling', 1.25)
    except Exception:
        pass

    default_font = tkfont.nametofont("TkDefaultFont")
    default_font.configure(size=11)
    text_font = tkfont.nametofont("TkTextFont")
    text_font.configure(size=11)
    fixed_font = tkfont.nametofont("TkFixedFont")
    fixed_font.configure(size=11)
    menu_font = tkfont.nametofont("TkMenuFont")
    menu_font.configure(size=11)
    heading_font = tkfont.nametofont("TkHeadingFont")
    heading_font.configure(size=12, weight="bold")

    style = ttk.Style(root)
    style.configure("TLabel", padding=(0, 6))
    style.configure("TButton", padding=(12, 8))
    style.configure("TCheckbutton", padding=(10, 6))
    style.configure("Horizontal.TProgressbar", thickness=16)

    OrganizadorGUI(root)
    root.mainloop()
