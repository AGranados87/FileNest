import tkinter as tk
from tkinter import ttk, filedialog, messagebox, font as tkfont
from pathlib import Path
import shutil
from collections import defaultdict
import threading
import json
import os
import sys
from datetime import datetime
import locale  # para nombre de mes en español
import base64
from io import BytesIO

# =========================
#  Utilidades de recursos
# =========================
def _find_project_root_with_images(start: Path) -> Path:
    for d in [start, *start.parents]:
        if (d / "images").exists() or (d / "Images").exists():
            return d
    return start

def resource_path(*parts) -> Path:
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass).joinpath(*parts)

    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent.joinpath(*parts)

    here = Path(__file__).resolve().parent
    root = _find_project_root_with_images(here)
    return root.joinpath(*parts)

# =========================
#  Configuración persistente
# =========================
LOGO_B64 = ""  # Fallback sin archivo

APP_DIR = Path(os.getenv('APPDATA', Path.home())) / "OrganizadorArchivos"
CONFIG_PATH = APP_DIR / "config.json"
LAST_RUN_PATH = APP_DIR / "last_run.json"  # para deshacer

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

def save_last_run(movidas):
    """movidas: lista de tuplas (dst, src) donde dst es nuevo y src el original."""
    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        data = [{"dst": d, "src": s} for d, s in movidas]
        LAST_RUN_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

def load_last_run():
    if LAST_RUN_PATH.exists():
        try:
            return json.loads(LAST_RUN_PATH.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []

def clear_last_run():
    try:
        if LAST_RUN_PATH.exists():
            LAST_RUN_PATH.unlink()
    except Exception:
        pass

# =========================
#  Config: carpetas y extensiones
# =========================
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

# Subcarpetas por fecha para ciertas categorías (lista de carpetas con fecha)
DATE_SUBFOLDERS = {
    "Excel": "%Y/%m",
    "Documentos Word": "%Y/%m",
    "Texto": "%Y/%m",
}

# =========================
#  Helpers de fecha/idioma
# =========================
def mes_nombre_es(dt: datetime) -> str:
    # Intenta varias locales comunes en Windows/Linux
    for loc in ("es_ES.UTF-8", "es_ES", "Spanish_Spain.1252", "Spanish_Spain"):
        try:
            locale.setlocale(locale.LC_TIME, loc)
            nombre = dt.strftime("%B")
            if nombre:
                return nombre.capitalize()
        except Exception:
            pass
    # Fallback manual si no hay locale española
    nombres = [
        "Enero","Febrero","Marzo","Abril","Mayo","Junio",
        "Julio","Agosto","Septiembre","Octubre","Noviembre","Diciembre"
    ]
    return nombres[dt.month - 1]

# =========================
#  Utilidades de archivo
# =========================
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
        # Usamos la fecha de modificación del archivo → Año / NombreMes, no la de creación.
        dt = datetime.fromtimestamp(p.stat().st_mtime)
        dest = dest / dt.strftime("%Y") / mes_nombre_es(dt)
    return dest

# =========================
#  Núcleo: organizar y analizar
# =========================
def organizar(ruta: Path, recursivo: bool, dry_run: bool, on_log, on_progress):
    ruta = ruta.expanduser().resolve()
    if not ruta.is_dir():
        raise ValueError(f"Ruta no válida: {ruta}")

    for carpeta in list(DESTINOS.keys()) + [CARPETA_OTROS]:
        (ruta / carpeta).mkdir(exist_ok=True)

    archivos = list(listar_archivos(ruta, recursivo))
    total = len(archivos)
    on_progress(0, total)

    movidos = defaultdict(int)
    errores = 0
    pares_movidos = []  # [(dst, src)]

    for i, p in enumerate(archivos, start=1):
        ext = p.suffix.casefold()
        carpeta = EXT_A_CARPETA.get(ext, CARPETA_OTROS)

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
                # Para deshacer: (nuevo, original)
                pares_movidos.append((str(destino), str(p)))
            movidos[carpeta] += 1
        except Exception as ex:
            errores += 1
            on_log(f"   ⚠️ Error moviendo '{p.name}': {ex}")

        on_progress(i, total)

    return movidos, errores, pares_movidos

def analizar(ruta: Path, recursivo: bool):
    ruta = ruta.expanduser().resolve()
    if not ruta.is_dir():
        raise ValueError(f"Ruta no válida: {ruta}")
    counts = defaultdict(int)
    total = 0
    for p in listar_archivos(ruta, recursivo):
        ext = p.suffix.casefold()
        carpeta = EXT_A_CARPETA.get(ext, CARPETA_OTROS)
        counts[carpeta] += 1
        total += 1
    return dict(sorted(counts.items())), total

# =========================
#  GUI
# =========================
class OrganizadorGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Organizador de archivos por tipo — FileNest")
        self.root.minsize(900, 560)
        self.root.geometry("1000x650")

        self.path_var = tk.StringVar(value=r"C:/Users/agran/OneDrive/Escritorio/auto_python")
        self.recursive_var = tk.BooleanVar(value=False)
        self.dry_run_var = tk.BooleanVar(value=False)

        # Cargar config
        self.config = load_config()

        self._build_ui()
        self._apply_prefs()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Bienvenida
        self._maybe_show_welcome()

    # ---------- Construcción UI ----------
    def _build_ui(self):
        # Menú superior
        menubar = tk.Menu(self.root)

        m_archivo = tk.Menu(menubar, tearoff=0)
        m_archivo.add_command(label="Organizar\tF5", command=self._run)
        m_archivo.add_command(label="Analizar\tCtrl+E", command=self._analizar)
        m_archivo.add_separator()
        m_archivo.add_command(label="Deshacer último", command=self._undo_last)
        m_archivo.add_separator()
        m_archivo.add_command(label="Salir", command=self.root.quit)

        m_ayuda = tk.Menu(menubar, tearoff=0)
        m_ayuda.add_command(label="Ayuda", command=self._show_welcome_modal)
        m_ayuda.add_command(label="Acerca de", command=self._acerca_de)

        menubar.add_cascade(label="Archivo", menu=m_archivo)
        menubar.add_cascade(label="Ayuda", menu=m_ayuda)
        self.root.config(menu=menubar)

        # Atajos
        self.root.bind("<F5>", lambda e: self._run())
        self.root.bind("<Control-e>", lambda e: self._analizar())
        self.root.bind("<Escape>", lambda e: self.root.quit())

        # Barra superior
        frm_top = ttk.Frame(self.root, padding=14)
        frm_top.pack(fill="x")

        ttk.Label(frm_top, text="Carpeta:").pack(side="left")
        self.entry_path = ttk.Entry(frm_top, textvariable=self.path_var)
        self.entry_path.pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(frm_top, text="Buscar…", command=self._browse).pack(side="left")

        # Opciones
        frm_opts = ttk.Frame(self.root, padding=(14, 0))
        frm_opts.pack(fill="x")
        ttk.Checkbutton(frm_opts, text="Recursivo (incluir subcarpetas)", variable=self.recursive_var).pack(side="left")
        ttk.Checkbutton(frm_opts, text="Simular (no mover)", variable=self.dry_run_var).pack(side="left", padx=(14, 0))

        # Progreso
        frm_prog = ttk.Frame(self.root, padding=(14, 10))
        frm_prog.pack(fill="x")
        self.progress = ttk.Progressbar(frm_prog, mode="determinate")
        self.progress.pack(fill="x", expand=True)
        self.lbl_status = ttk.Label(frm_prog, text="Listo.")
        self.lbl_status.pack(anchor="w", pady=(6, 0))

        # Resumen (análisis)
        frm_summary = ttk.Frame(self.root, padding=(14, 0))
        frm_summary.pack(fill="x")
        self.lbl_summary = ttk.Label(frm_summary, text="Sin análisis.")
        self.lbl_summary.pack(side="left")
        ttk.Button(frm_summary, text="Analizar", command=self._analizar).pack(side="right")

        # Log
        frm_log = ttk.Frame(self.root, padding=14)
        frm_log.pack(fill="both", expand=True)
        self.txt_log = tk.Text(frm_log, height=16, wrap="none")
        yscroll = tk.Scrollbar(frm_log, orient="vertical", command=self.txt_log.yview, width=18)
        self.txt_log.configure(yscrollcommand=yscroll.set)
        self.txt_log.pack(side="left", fill="both", expand=True)
        yscroll.pack(side="right", fill="y")

        # Botones inferiores
        frm_btns = ttk.Frame(self.root, padding=14)
        frm_btns.pack(fill="x")
        self.btn_run = ttk.Button(frm_btns, text="Organizar", command=self._run)
        self.btn_run.pack(side="left")

        self.btn_undo = ttk.Button(frm_btns, text="Deshacer último", command=self._undo_last)
        self.btn_undo.pack(side="left", padx=(8, 0))

        ttk.Button(frm_btns, text="Salir", command=self.root.quit).pack(side="right")
        ttk.Button(frm_btns, text="Acerca de", command=self._acerca_de).pack(side="right", padx=(0, 8))
        ttk.Button(frm_btns, text="Ayuda", command=self._show_welcome_modal).pack(side="right", padx=(0, 8))

        self._toggle_undo_button()

    # ---------- Helpers UI ----------
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

    # ---------- Acciones ----------
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
                movidos, errores, pares_movidos = organizar(
                    ruta, rec, dry,
                    on_log=lambda m: self.root.after(0, self._log, m),
                    on_progress=lambda c, t: self.root.after(0, self._set_progress, c, t),
                )
                if not dry and pares_movidos:
                    # para deshacer movemos en sentido inverso (nuevo -> original)
                    save_last_run(pares_movidos)

                resumen = "\nResumen:\n" + "\n".join(f"  {k}: {v}" for k, v in sorted(movidos.items()))
                if errores:
                    resumen += f"\n  Errores: {errores}"
                self.root.after(0, self._log, resumen)
                self.root.after(0, self.lbl_status.configure, {"text": "Completado."})
                self.root.after(0, self.btn_run.configure, {"state": "normal"})
                self.root.after(0, self._toggle_undo_button)

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

    def _analizar(self):
        try:
            ruta = Path(self.path_var.get())
            rec = self.recursive_var.get()
            counts, total = analizar(ruta, rec)
            resumen = " • ".join([f"{k}: {v}" for k, v in counts.items()]) or "Nada que organizar."
            self.lbl_summary.configure(text=f"Análisis ({total} archivos): {resumen}")
            self._log(f"[Análisis] Total={total} → " + (resumen if resumen else "—"))
        except Exception as ex:
            messagebox.showerror("Análisis", str(ex))

    # ---------- Deshacer ----------
    def _toggle_undo_button(self):
        has_last = bool(load_last_run())
        self.btn_undo.configure(state="normal" if has_last else "disabled")

    def _undo_last(self):
        plan = load_last_run()
        if not plan:
            messagebox.showinfo("Deshacer", "No hay operaciones para deshacer.")
            self._toggle_undo_button()
            return

        errores = 0
        for par in plan:
            dst = Path(par["dst"])  # archivo actualmente en destino
            src = Path(par["src"])  # ruta original
            try:
                src.parent.mkdir(parents=True, exist_ok=True)
                final = ruta_unica(src)
                shutil.move(str(dst), str(final))
                self._log(f"Deshecho: {dst.name} → {final}")
            except Exception as ex:
                errores += 1
                self._log(f"   ⚠️ Error deshaciendo '{dst.name}': {ex}")

        clear_last_run()
        self._toggle_undo_button()
        if errores:
            messagebox.showwarning("Deshacer", f"Terminado con {errores} errores.")
        else:
            messagebox.showinfo("Deshacer", "Deshecho completo.")

    # ==========
    #  Imágenes (helpers)
    # ==========
    def _load_logo_from_file(self, path: Path, size=(40, 40)):
        """Carga logo desde archivo; intenta PIL para reescalar y cae a tk.PhotoImage si falta PIL."""
        try:
            from PIL import Image, ImageTk
            im = Image.open(path).convert("RGBA").resize(size, Image.LANCZOS)
            return ImageTk.PhotoImage(im)
        except Exception:
            try:
                # Fallback sin reescalar
                return tk.PhotoImage(file=str(path))
            except Exception:
                return None

    def _load_logo_embedded(self, b64_str: str, size=(40, 40)):
        if not b64_str:
            return None
        # Intento con PIL
        try:
            from PIL import Image, ImageTk
            data = base64.b64decode(b64_str)
            im = Image.open(BytesIO(data)).convert("RGBA")
            if size:
                im = im.resize(size, Image.LANCZOS)
            return ImageTk.PhotoImage(im)
        except Exception:
            try:
                return tk.PhotoImage(data=b64_str)
            except Exception:
                return None

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

    # ---------- Bienvenida / Ayuda ----------
    def _maybe_show_welcome(self):
        if not self.config.get("suppress_welcome_v2", False):
            self._show_welcome_modal()

    def _show_welcome_modal(self):
        win = tk.Toplevel(self.root)
        win.title("Cómo funciona")
        win.transient(self.root)
        win.grab_set()  # modal
        win.resizable(False, False)

        outer = ttk.Frame(win, padding=18)
        outer.pack(fill="both", expand=True)

        content = ttk.Frame(outer)
        content.pack(fill="both", expand=True)
        content.columnconfigure(0, weight=0)
        content.columnconfigure(1, weight=1)

        logo_path = resource_path("images", "FileNest.png")
        self.logo_help = None
        if logo_path.exists():
            self.logo_help = self._load_logo_from_file(logo_path, (150, 150))
        elif LOGO_B64:
            self.logo_help = self._load_logo_embedded(LOGO_B64, (64, 64))
        if self.logo_help:
            ttk.Label(content, image=self.logo_help).grid(row=0, column=0, padx=(0, 14), pady=(0, 6), sticky="n")

        texto = (
            "¿Qué hace FileNest?\n"
            "• Crea carpetas: Imágenes, PDFs, Vídeos, Documentos Word, Excel, Texto y Otros.\n"
            "• Mueve tus archivos a la carpeta según su extensión.\n"
            "• Evita tocar lo que ya esté dentro de esas carpetas.\n"
            "• Si el nombre existe, renombra a (1), (2), … para evitar colisiones.\n"
            "• En 'Excel', 'Documentos Word' y 'Texto' además organiza en subcarpetas por fecha (AAAA/NombreMes) "
            "según la fecha de modificación.\n\n"
            "Opciones:\n"
            "• Recursivo: incluye subcarpetas.\n"
            "• Simular: no mueve nada, solo muestra el plan.\n\n"
            "Consejo: prueba primero con Simular (por si acaso 😉)."
        )
        ttk.Label(content, text=texto, justify="left", wraplength=560).grid(row=0, column=1, sticky="w")

        self.no_mostrar_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(outer, text="No volver a mostrar al iniciar", variable=self.no_mostrar_var)\
            .pack(anchor="w", pady=(10, 0))

        btns = ttk.Frame(outer)
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
        import webbrowser

        url = "https://ko-fi.com/alvarogr87"

        logo_path = resource_path("images", "FileNest.png")

        self.logo_about = None
        if logo_path.exists():
            self.logo_about = self._load_logo_from_file(logo_path, (150, 150))
        elif LOGO_B64:
            self.logo_about = self._load_logo_embedded(LOGO_B64, (40, 40))

        # Ventana modal
        win = tk.Toplevel(self.root)
        win.title("Acerca de")
        win.transient(self.root)
        win.grab_set()  # modal
        win.resizable(False, False)

        outer = ttk.Frame(win, padding=18)
        outer.pack(fill="both", expand=True)

        # Layout en dos columnas: [logo] | [texto]
        content = ttk.Frame(outer)
        content.pack(fill="both", expand=True)
        content.columnconfigure(0, weight=0)
        content.columnconfigure(1, weight=1)

        # Logo pequeño a la izquierda
        if self.logo_about:
            ttk.Label(content, image=self.logo_about).grid(
                row=0, column=0, padx=(0, 12), pady=(2, 2), sticky="n"
            )
        else:
            ttk.Label(content, text="").grid(row=0, column=0, padx=(0, 12), sticky="n")

        # Texto a la derecha
        right = ttk.Frame(content)
        right.grid(row=0, column=1, sticky="nw")

        ttk.Label(right, text="Organizador de archivos — versión básica",
                  font=("Segoe UI", 12, "bold")).pack(anchor="w")
        ttk.Label(right, text="Desarrollado por Álvaro Granados Ruiz.")\
            .pack(anchor="w", pady=(4, 0))
        ttk.Label(right, text="Sin anuncios. No se venderá. Solo utilidad y cariño 😉",
                  wraplength=520, justify="left").pack(anchor="w", pady=(0, 8))

        ttk.Separator(outer).pack(fill="x", pady=8)

        ttk.Label(outer, text="¿Te ha ahorrado tiempo? Puedes invitarme a un café:")\
            .pack(anchor="w")

        link = ttk.Label(outer, text=url, foreground="blue", cursor="hand2")
        link.pack(anchor="w", pady=(2, 8))
        link.bind("<Button-1>", lambda e: webbrowser.open(url))

        btns = ttk.Frame(outer)
        btns.pack(fill="x")
        ttk.Button(btns, text="☕ Invitar en Ko-fi",
                   command=lambda: webbrowser.open(url)).pack(side="right")
        ttk.Button(btns, text="Cerrar", command=win.destroy).pack(side="right", padx=(0, 8))

        try:
            self._center_child(win)
            self.root.after(0, lambda: self._center_child(win))
        except Exception:
            win.update_idletasks()
            x = self.root.winfo_rootx() + (self.root.winfo_width() - win.winfo_width()) // 2
            y = self.root.winfo_rooty() + (self.root.winfo_height() - win.winfo_height()) // 2
            win.geometry(f"+{x}+{y}")

    # ---------- Preferencias ----------
    def _apply_prefs(self):
        # Ruta
        last_path = self.config.get("last_path")
        if last_path and Path(last_path).exists():
            self.path_var.set(last_path)

        # Flags
        if "recursive" in self.config:
            self.recursive_var.set(bool(self.config["recursive"]))
        if "dry_run" in self.config:
            self.dry_run_var.set(bool(self.config["dry_run"]))

        # Geometría
        geo = self.config.get("geometry")
        if geo:
            try:
                self.root.geometry(geo)
            except Exception:
                pass

    def _on_close(self):
        # Guardar preferencias mínimas
        self.config["last_path"] = self.path_var.get()
        self.config["recursive"] = self.recursive_var.get()
        self.config["dry_run"] = self.dry_run_var.get()
        try:
            self.config["geometry"] = self.root.winfo_geometry()
        except Exception:
            pass
        save_config(self.config)
        self.root.destroy()

# =========================
#  main
# =========================
if __name__ == "__main__":
    root = tk.Tk()

    # DPI y escalado
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    try:
        root.tk.call('tk', 'scaling', 1.25)
    except Exception:
        pass

    # Tipografías base
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

    # Estilos ttk
    style = ttk.Style(root)
    style.configure("TLabel", padding=(0, 6))
    style.configure("TButton", padding=(12, 8))
    style.configure("TCheckbutton", padding=(10, 6))
    style.configure("Horizontal.TProgressbar", thickness=16)

    OrganizadorGUI(root)
    root.mainloop()
