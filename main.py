import tkinter as tk
from tkinter import ttk, colorchooser, filedialog, messagebox, simpledialog
import math
import json
import os

#  Pillow (PIL) 
try:
    from PIL import Image, ImageDraw, ImageTk, ImageFont, ImageFilter
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("⚠  Pillow not found. Install with: pip install Pillow")

#  Anthropic (optional AI feature) 
try:
    import anthropic
    import base64
    import io
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False


#  THEME DEFINITIONS

THEMES = {
    "dark": {
        "bg":           "#1a1a2e",
        "toolbar_bg":   "#16213e",
        "sidebar_bg":   "#0f3460",
        "canvas_bg":    "#ffffff",
        "btn_bg":       "#1a1a2e",
        "btn_active":   "#e94560",
        "btn_fg":       "#e0e0e0",
        "accent":       "#e94560",
        "accent2":      "#0f3460",
        "text":         "#e0e0e0",
        "text_dim":     "#888",
        "border":       "#333355",
        "slider_trough":"#333",
        "status_bg":    "#0d0d1a",
    },
    "light": {
        "bg":           "#f0f4f8",
        "toolbar_bg":   "#dde8f0",
        "sidebar_bg":   "#c8daea",
        "canvas_bg":    "#ffffff",
        "btn_bg":       "#dde8f0",
        "btn_active":   "#4a90d9",
        "btn_fg":       "#1a1a2e",
        "accent":       "#4a90d9",
        "accent2":      "#b3d4ea",
        "text":         "#1a1a2e",
        "text_dim":     "#666",
        "border":       "#b0c4d8",
        "slider_trough":"#ccc",
        "status_bg":    "#c0d4e4",
    }
}


#  TOOL MANAGER  — tracks active tool and its state

class ToolManager:
    """Manages active tool, brush settings, and drawing state."""

    TOOLS = ["✏️ Pen", "🖊️ Marker", "🧹 Eraser", "📏 Line",
             "▭ Rect", "⭕ Circle", "🪣 Fill", "T Text", "🔲 Grid"]

    def __init__(self):
        self.tool          = "✏️ Pen"
        self.color         = "#000000"
        self.bg_color      = "#ffffff"
        self.brush_size    = 4
        self.opacity       = 255          # 0-255
        self.grid_on       = False
        self.grid_size     = 30

        # shape preview temps
        self.start_x = 0
        self.start_y = 0
        self.preview_item = None

    def get_draw_color(self):
        """Return color with opacity prefix (used for canvas)."""
        if self.tool == "🧹 Eraser":
            return self.bg_color
        return self.color

    def get_pil_color(self):
        """Return RGBA tuple for PIL drawing."""
        if self.tool == "🧹 Eraser":
            return self._hex_to_rgba(self.bg_color)
        return self._hex_to_rgba(self.color, self.opacity)

    def _hex_to_rgba(self, hex_color, alpha=255):
        hex_color = hex_color.lstrip('#')
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        return (r, g, b, alpha)


#  CANVAS MANAGER  — wraps Tkinter Canvas + PIL image sync

class CanvasManager:
    """
    Dual-buffer drawing system:
      • Tkinter Canvas  →  fast live preview
      • PIL Image       →  high-quality persistent bitmap (for save/undo)
    """

    def __init__(self, parent, tool_manager, width=900, height=620):
        self.tm      = tool_manager
        self.width   = width
        self.height  = height
        self.undo_stack = []      # list of PIL Image snapshots
        self.MAX_UNDO   = 30

        #  Tkinter Canvas 
        self.canvas = tk.Canvas(
            parent,
            width=width, height=height,
            bg=tool_manager.bg_color,
            cursor="crosshair",
            bd=0, highlightthickness=0
        )

        # PIL backing image 
        self._reset_pil()

        # last mouse position for smooth strokes
        self._last_x = None
        self._last_y = None

        # bind mouse events
        self.canvas.bind("<Button-1>",        self._on_press)
        self.canvas.bind("<B1-Motion>",       self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)

    #  PIL init / reset 
    def _reset_pil(self):
        """Create a fresh white PIL image."""
        self.pil_image = Image.new("RGBA", (self.width, self.height),
                                   self.tm.bg_color + "ff" if len(self.tm.bg_color) == 7
                                   else self.tm.bg_color)
        self.pil_draw  = ImageDraw.Draw(self.pil_image, "RGBA")

    #  Undo support 
    def push_undo(self):
        """Snapshot current PIL image onto undo stack."""
        if len(self.undo_stack) >= self.MAX_UNDO:
            self.undo_stack.pop(0)
        self.undo_stack.append(self.pil_image.copy())

    def undo(self):
        if not self.undo_stack:
            return
        self.pil_image = self.undo_stack.pop()
        self.pil_draw  = ImageDraw.Draw(self.pil_image, "RGBA")
        self._refresh_canvas()

    #  Canvas → PIL sync 
    def _refresh_canvas(self):
        """Redraw Tkinter Canvas from PIL image."""
        self._tk_image = ImageTk.PhotoImage(self.pil_image)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self._tk_image)
        self._draw_grid()

    def _draw_grid(self):
        if not self.tm.grid_on:
            return
        gs = self.tm.grid_size
        for x in range(0, self.width, gs):
            self.canvas.create_line(x, 0, x, self.height,
                                    fill="#cccccc55", dash=(2, 4))
        for y in range(0, self.height, gs):
            self.canvas.create_line(0, y, self.width, y,
                                    fill="#cccccc55", dash=(2, 4))

    # Mouse event handlers 
    def _on_press(self, event):
        self.push_undo()
        x, y = event.x, event.y
        self.tm.start_x, self.tm.start_y = x, y
        self._last_x, self._last_y = x, y

        if self.tm.tool == "🪣 Fill":
            self._flood_fill(x, y)
        elif self.tm.tool == "T Text":
            self._insert_text(x, y)

    def _on_drag(self, event):
        x, y = event.x, event.y
        tool  = self.tm.tool
        color = self.tm.get_draw_color()
        size  = self.tm.brush_size

        if tool in ("✏️ Pen", "🧹 Eraser"):
            # smooth freehand stroke
            if self._last_x is not None:
                self.canvas.create_line(
                    self._last_x, self._last_y, x, y,
                    fill=color, width=size,
                    capstyle=tk.ROUND, joinstyle=tk.ROUND, smooth=True
                )
                self.pil_draw.line(
                    [self._last_x, self._last_y, x, y],
                    fill=self.tm.get_pil_color(),
                    width=size
                )
            self._last_x, self._last_y = x, y

        elif tool == "🖊️ Marker":
            # semi-transparent marker
            if self._last_x is not None:
                self.canvas.create_line(
                    self._last_x, self._last_y, x, y,
                    fill=color, width=size * 3,
                    capstyle=tk.ROUND, stipple="gray50"
                )
                marker_color = self.tm._hex_to_rgba(self.tm.color, 120)
                self.pil_draw.line(
                    [self._last_x, self._last_y, x, y],
                    fill=marker_color, width=size * 3
                )
            self._last_x, self._last_y = x, y

        elif tool in ("📏 Line", "▭ Rect", "⭕ Circle"):
            # live shape preview — redraw from PIL
            self._refresh_canvas()
            sx, sy = self.tm.start_x, self.tm.start_y
            if tool == "📏 Line":
                self.canvas.create_line(sx, sy, x, y,
                                        fill=color, width=size,
                                        capstyle=tk.ROUND)
            elif tool == "▭ Rect":
                self.canvas.create_rectangle(sx, sy, x, y,
                                             outline=color, width=size)
            elif tool == "⭕ Circle":
                self.canvas.create_oval(sx, sy, x, y,
                                        outline=color, width=size)

    def _on_release(self, event):
        x, y  = event.x, event.y
        tool  = self.tm.tool
        sx, sy = self.tm.start_x, self.tm.start_y
        pil_c = self.tm.get_pil_color()
        size  = self.tm.brush_size

        if tool == "📏 Line":
            self.pil_draw.line([sx, sy, x, y], fill=pil_c, width=size)
        elif tool == "▭ Rect":
            self.pil_draw.rectangle([sx, sy, x, y], outline=pil_c, width=size)
        elif tool == "⭕ Circle":
            self.pil_draw.ellipse([sx, sy, x, y], outline=pil_c, width=size)

        self._last_x = None
        self._last_y = None
        self._refresh_canvas()

    #  Flood fill 
    def _flood_fill(self, x, y):
        """Seed-fill using PIL ImageDraw.floodfill."""
        if not PIL_AVAILABLE:
            return
        try:
            # work on RGB copy for floodfill (RGBA has issues)
            rgb   = self.pil_image.convert("RGB")
            target_color = rgb.getpixel((x, y))
            fill_rgba    = self.tm.get_pil_color()[:3]
            if target_color == fill_rgba:
                return
            ImageDraw.floodfill(rgb, (x, y), fill_rgba, thresh=40)
            # merge back
            self.pil_image = rgb.convert("RGBA")
            self.pil_draw  = ImageDraw.Draw(self.pil_image, "RGBA")
            self._refresh_canvas()
        except Exception as e:
            print(f"Fill error: {e}")

    #  Text insertion 
    def _insert_text(self, x, y):
        text = simpledialog.askstring("Insert Text", "Enter text:",
                                      parent=self.canvas)
        if text:
            self.canvas.create_text(x, y, text=text,
                                    fill=self.tm.color,
                                    font=("Arial", self.tm.brush_size * 3))
            try:
                font = ImageFont.truetype("arial.ttf", self.tm.brush_size * 3)
            except Exception:
                font = ImageFont.load_default()
            self.pil_draw.text((x, y), text,
                               fill=self.tm.get_pil_color(), font=font)
            self._refresh_canvas()

    #  Clear canvas 
    def clear(self):
        self.push_undo()
        bg = self.tm.bg_color
        self.canvas.config(bg=bg)
        self.canvas.delete("all")
        self.pil_image = Image.new("RGBA", (self.width, self.height), bg)
        self.pil_draw  = ImageDraw.Draw(self.pil_image, "RGBA")
        self._draw_grid()

    #  Open image 
    def open_image(self, filepath):
        self.push_undo()
        img = Image.open(filepath).convert("RGBA")
        img = img.resize((self.width, self.height), Image.LANCZOS)
        self.pil_image = img
        self.pil_draw  = ImageDraw.Draw(self.pil_image, "RGBA")
        self._refresh_canvas()

    #  Save / Export 
    def save(self, filepath):
        ext = os.path.splitext(filepath)[1].lower()
        img = self.pil_image.convert("RGB")
        if ext == ".pdf":
            img.save(filepath, "PDF", resolution=100.0)
        elif ext == ".jpg" or ext == ".jpeg":
            img.save(filepath, "JPEG", quality=95)
        else:
            img.save(filepath, "PNG")

    #  Get PNG bytes for AI 
    def get_png_bytes(self):
        buf = io.BytesIO()
        self.pil_image.convert("RGB").save(buf, "PNG")
        return buf.getvalue()


#  DRAWING APP  — main window and UI

class DrawingApp:
    """Main application class — owns the root window and all widgets."""

    PALETTE = [
        "#000000", "#ffffff", "#ff0000", "#00aa00",
        "#0000ff", "#ffff00", "#ff8800", "#aa00aa",
        "#00aaaa", "#888888", "#ff6699", "#336699",
        "#99cc00", "#cc6600", "#6600cc", "#009966",
    ]

    def __init__(self):
        self.theme_name = "dark"
        self.T = THEMES[self.theme_name]

        # Root window 
        self.root = tk.Tk()
        self.root.title("✏️  SketchPad Pro")
        self.root.geometry("1200x780")
        self.root.minsize(900, 600)
        self.root.configure(bg=self.T["bg"])

        try:
            self.root.iconbitmap("")
        except Exception:
            pass

        #  Managers 
        self.tm = ToolManager()

        #  Build UI 
        self._build_toolbar()
        self._build_main_area()
        self._build_status_bar()
        self._apply_theme()

        #  Keyboard shortcuts 
        self.root.bind("<Control-s>", lambda e: self._save())
        self.root.bind("<Control-z>", lambda e: self.cm.undo())
        self.root.bind("<Control-n>", lambda e: self._new_canvas())
        self.root.bind("<Control-o>", lambda e: self._open_image())

        # update status bar every 500 ms
        self._update_status()

    #  UI BUILDER METHODS

    def _build_toolbar(self):
        """Top toolbar with tools, actions, and settings."""
        self.toolbar = tk.Frame(self.root, height=56, bd=0)
        self.toolbar.pack(side="top", fill="x")
        self.toolbar.pack_propagate(False)

        #  Left: Logo 
        logo = tk.Label(self.toolbar, text="✏️ SketchPad Pro",
                        font=("Segoe UI", 13, "bold"), padx=12)
        logo.pack(side="left", pady=8)

        #  Separator 
        self._vsep(self.toolbar)

        #  Tool buttons 
        self.tool_buttons = {}
        for tool in ToolManager.TOOLS:
            if tool == "🔲 Grid":
                continue   # grid handled separately
            btn = tk.Button(
                self.toolbar, text=tool,
                font=("Segoe UI", 9),
                relief="flat", bd=0, padx=8, pady=6,
                cursor="hand2",
                command=lambda t=tool: self._select_tool(t)
            )
            btn.pack(side="left", padx=2, pady=6)
            self.tool_buttons[tool] = btn

        #  Separator 
        self._vsep(self.toolbar)

        #  Action buttons 
        actions = [
            ("↩ Undo",    self.cm_undo),
            ("🗑 Clear",   self._new_canvas),
            ("📂 Open",   self._open_image),
            ("💾 Save",   self._save),
        ]
        self.action_btns = {}
        for label, cmd in actions:
            btn = tk.Button(self.toolbar, text=label,
                            font=("Segoe UI", 9),
                            relief="flat", bd=0, padx=8, pady=6,
                            cursor="hand2", command=cmd)
            btn.pack(side="left", padx=2, pady=6)
            self.action_btns[label] = btn

        #  Right side: theme + grid 
        self._vsep(self.toolbar)

        self.grid_var = tk.BooleanVar(value=False)
        grid_btn = tk.Checkbutton(
            self.toolbar, text="⊞ Grid",
            variable=self.grid_var,
            font=("Segoe UI", 9),
            relief="flat", bd=0, padx=6,
            command=self._toggle_grid, cursor="hand2"
        )
        grid_btn.pack(side="left", padx=4, pady=6)
        self.grid_chk = grid_btn

        if ANTHROPIC_AVAILABLE:
            self._vsep(self.toolbar)
            ai_btn = tk.Button(
                self.toolbar, text="🤖 AI Analyze",
                font=("Segoe UI", 9, "bold"),
                relief="flat", bd=0, padx=10, pady=6,
                cursor="hand2", command=self._ai_analyze
            )
            ai_btn.pack(side="left", padx=4, pady=6)
            self.action_btns["🤖 AI Analyze"] = ai_btn

        # theme switch (right-aligned)
        self.theme_btn = tk.Button(
            self.toolbar, text="🌙 Dark",
            font=("Segoe UI", 9),
            relief="flat", bd=0, padx=10, pady=6,
            cursor="hand2", command=self._toggle_theme
        )
        self.theme_btn.pack(side="right", padx=8, pady=6)

    def _build_main_area(self):
        """Left sidebar + central canvas."""
        self.main_frame = tk.Frame(self.root, bd=0)
        self.main_frame.pack(fill="both", expand=True)

        # ── Sidebar (left) ───────────────────────────────
        self.sidebar = tk.Frame(self.main_frame, width=160, bd=0)
        self.sidebar.pack(side="left", fill="y", padx=0)
        self.sidebar.pack_propagate(False)

        self._build_sidebar()

        #  Canvas area 
        canvas_frame = tk.Frame(self.main_frame, bd=0)
        canvas_frame.pack(side="left", fill="both", expand=True, padx=8, pady=8)

        # scroll support
        self.canvas_scroll_x = tk.Scrollbar(canvas_frame, orient="horizontal")
        self.canvas_scroll_y = tk.Scrollbar(canvas_frame, orient="vertical")
        self.canvas_scroll_x.pack(side="bottom", fill="x")
        self.canvas_scroll_y.pack(side="right",  fill="y")

        inner = tk.Frame(canvas_frame, bd=2, relief="flat")
        inner.pack(fill="both", expand=True)

        self.cm = CanvasManager(inner, self.tm, width=900, height=620)
        self.cm.canvas.pack(fill="both", expand=True)
        self.cm.canvas.configure(
            xscrollcommand=self.canvas_scroll_x.set,
            yscrollcommand=self.canvas_scroll_y.set
        )

    def _build_sidebar(self):
        """Color palette, brush controls, canvas bg picker."""

        def section_label(text):
            tk.Label(self.sidebar, text=text,
                     font=("Segoe UI", 8, "bold"),
                     anchor="w", padx=10).pack(fill="x", pady=(10, 2))

        #  Color preview 
        section_label("ACTIVE COLOR")
        self.color_preview = tk.Canvas(self.sidebar,
                                       width=120, height=36,
                                       bd=0, highlightthickness=1,
                                       cursor="hand2")
        self.color_preview.pack(padx=16, pady=4)
        self.color_preview.bind("<Button-1>", lambda e: self._pick_color())

        #  Palette grid 
        section_label("PALETTE")
        palette_frame = tk.Frame(self.sidebar)
        palette_frame.pack(padx=10)
        for i, c in enumerate(self.PALETTE):
            btn = tk.Canvas(palette_frame, width=22, height=22,
                            bg=c, cursor="hand2",
                            bd=0, highlightthickness=1,
                            highlightbackground="#555")
            btn.grid(row=i//4, column=i%4, padx=2, pady=2)
            btn.bind("<Button-1>", lambda e, col=c: self._set_color(col))

        #  Brush size 
        section_label("BRUSH SIZE")
        self.size_var = tk.IntVar(value=self.tm.brush_size)
        size_slider = ttk.Scale(self.sidebar, from_=1, to=60,
                                variable=self.size_var,
                                orient="horizontal",
                                command=self._on_size_change)
        size_slider.pack(fill="x", padx=14, pady=2)
        self.size_label = tk.Label(self.sidebar,
                                   text=f"Size: {self.tm.brush_size}px",
                                   font=("Segoe UI", 8))
        self.size_label.pack()

        # Brush preview dot
        self.brush_preview = tk.Canvas(self.sidebar, width=70, height=70,
                                       bd=0, highlightthickness=0)
        self.brush_preview.pack(pady=4)

        #  Opacity 
        section_label("OPACITY")
        self.opacity_var = tk.IntVar(value=255)
        opacity_slider = ttk.Scale(self.sidebar, from_=10, to=255,
                                   variable=self.opacity_var,
                                   orient="horizontal",
                                   command=self._on_opacity_change)
        opacity_slider.pack(fill="x", padx=14, pady=2)
        self.opacity_label = tk.Label(self.sidebar,
                                      text="100%", font=("Segoe UI", 8))
        self.opacity_label.pack()

        #  Canvas background 
        section_label("CANVAS BG")
        bg_btn = tk.Button(self.sidebar, text="🎨 Change BG",
                           font=("Segoe UI", 8),
                           relief="flat", bd=0, pady=4,
                           cursor="hand2",
                           command=self._change_canvas_bg)
        bg_btn.pack(fill="x", padx=14, pady=4)
        self.sidebar_bg_btn = bg_btn

        #  Export format 
        section_label("EXPORT AS")
        export_frame = tk.Frame(self.sidebar)
        export_frame.pack(padx=10, pady=4)
        for fmt in ["PNG", "JPG", "PDF"]:
            tk.Button(export_frame, text=fmt,
                      font=("Segoe UI", 8), relief="flat", bd=0,
                      padx=6, pady=3, cursor="hand2",
                      command=lambda f=fmt: self._save(fmt=f)
                      ).pack(side="left", padx=2)

        self._update_brush_preview()
        self._update_color_preview()

    def _build_status_bar(self):
        """Bottom status bar."""
        self.status_bar = tk.Frame(self.root, height=26, bd=0)
        self.status_bar.pack(side="bottom", fill="x")
        self.status_bar.pack_propagate(False)

        self.status_label = tk.Label(
            self.status_bar,
            text="", font=("Segoe UI", 8),
            anchor="w", padx=12
        )
        self.status_label.pack(side="left", fill="y")

        # Coords label (right side)
        self.coord_label = tk.Label(
            self.status_bar, text="",
            font=("Segoe UI", 8), padx=12
        )
        self.coord_label.pack(side="right", fill="y")
        self.cm.canvas.bind("<Motion>", self._on_mouse_move)

    #  EVENT / ACTION HANDLERS

    def cm_undo(self):
        self.cm.undo()

    def _select_tool(self, tool):
        self.tm.tool = tool
        self._highlight_tool(tool)
        if tool == "🧹 Eraser":
            self.cm.canvas.config(cursor="circle")
        else:
            self.cm.canvas.config(cursor="crosshair")

    def _highlight_tool(self, active):
        for name, btn in self.tool_buttons.items():
            if name == active:
                btn.configure(bg=self.T["accent"], fg="#ffffff")
            else:
                btn.configure(bg=self.T["btn_bg"], fg=self.T["btn_fg"])

    def _pick_color(self):
        color = colorchooser.askcolor(color=self.tm.color,
                                      title="Pick a color")[1]
        if color:
            self._set_color(color)

    def _set_color(self, color):
        self.tm.color = color
        self._update_color_preview()
        self._update_brush_preview()

    def _on_size_change(self, val):
        self.tm.brush_size = int(float(val))
        self.size_label.config(text=f"Size: {self.tm.brush_size}px")
        self._update_brush_preview()

    def _on_opacity_change(self, val):
        self.tm.opacity = int(float(val))
        pct = int(self.tm.opacity / 255 * 100)
        self.opacity_label.config(text=f"{pct}%")

    def _toggle_grid(self):
        self.tm.grid_on = self.grid_var.get()
        self.cm._refresh_canvas()

    def _change_canvas_bg(self):
        color = colorchooser.askcolor(color=self.tm.bg_color,
                                      title="Canvas background")[1]
        if color:
            self.tm.bg_color = color
            self.cm.canvas.config(bg=color)
            # update the PIL image background (only unfilled areas)
            # simplest: just set bg_color so eraser uses it

    def _new_canvas(self):
        if messagebox.askyesno("New Canvas",
                               "Clear the canvas? (Undo is available)"):
            self.cm.clear()

    def _open_image(self):
        path = filedialog.askopenfilename(
            title="Open Image",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp *.gif *.tiff"),
                       ("All files", "*.*")]
        )
        if path:
            self.cm.open_image(path)

    def _save(self, fmt=None):
        if fmt:
            ext_map = {"PNG": ".png", "JPG": ".jpg", "PDF": ".pdf"}
            ext = ext_map.get(fmt, ".png")
            filetypes = [(f"{fmt} file", f"*{ext}")]
        else:
            ext = ".png"
            filetypes = [
                ("PNG image",  "*.png"),
                ("JPEG image", "*.jpg"),
                ("PDF file",   "*.pdf"),
                ("All files",  "*.*"),
            ]
        path = filedialog.asksaveasfilename(
            defaultextension=ext,
            filetypes=filetypes,
            title="Save Drawing"
        )
        if path:
            self.cm.save(path)
            messagebox.showinfo("Saved", f"Drawing saved to:\n{path}")

    #  AI Analysis 
    def _ai_analyze(self):
        if not ANTHROPIC_AVAILABLE:
            messagebox.showinfo("AI Unavailable",
                                "Install: pip install anthropic")
            return
        if not PIL_AVAILABLE:
            messagebox.showinfo("PIL Required",
                                "Install: pip install Pillow")
            return

        try:
            png_bytes = self.cm.get_png_bytes()
            b64_data  = base64.standard_b64encode(png_bytes).decode("utf-8")

            popup = tk.Toplevel(self.root)
            popup.title("🤖 AI Sketch Analyzer")
            popup.geometry("440x300")
            popup.configure(bg=self.T["bg"])
            popup.grab_set()

            tk.Label(popup, text="🤖 AI Sketch Analyzer",
                     font=("Segoe UI", 13, "bold"),
                     bg=self.T["bg"], fg=self.T["accent"]).pack(pady=12)

            result_text = tk.Text(popup, wrap="word",
                                  font=("Segoe UI", 10),
                                  bg=self.T["sidebar_bg"],
                                  fg=self.T["text"],
                                  bd=0, padx=12, pady=8,
                                  relief="flat", height=10)
            result_text.pack(fill="both", expand=True, padx=16, pady=4)
            result_text.insert("end", "Analyzing your sketch…\n")

            def run_ai():
                try:
                    client = anthropic.Anthropic()
                    msg = client.messages.create(
                        model="claude-sonnet-4-6",
                        max_tokens=512,
                        messages=[{
                            "role": "user",
                            "content": [
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": "image/png",
                                        "data": b64_data,
                                    }
                                },
                                {
                                    "type": "text",
                                    "text": (
                                        "You are an AI sketch analyzer. "
                                        "Look at this drawing and:\n"
                                        "1. Identify what object(s) or scene this might be\n"
                                        "2. Describe what you see\n"
                                        "3. Give a confidence level (high/medium/low)\n"
                                        "4. Offer one short creative tip to improve the sketch\n\n"
                                        "Be concise and friendly. If the canvas appears blank or "
                                        "nearly blank, say so and encourage the user to draw something."
                                    )
                                }
                            ]
                        }]
                    )
                    result = msg.content[0].text
                    result_text.config(state="normal")
                    result_text.delete("1.0", "end")
                    result_text.insert("end", result)
                    result_text.config(state="disabled")
                except Exception as err:
                    result_text.config(state="normal")
                    result_text.delete("1.0", "end")
                    result_text.insert("end", f"Error: {err}")
                    result_text.config(state="disabled")

            self.root.after(100, run_ai)
            tk.Button(popup, text="Close",
                      command=popup.destroy,
                      bg=self.T["accent"], fg="#fff",
                      relief="flat", padx=16, pady=6,
                      cursor="hand2"
                      ).pack(pady=8)

        except Exception as e:
            messagebox.showerror("AI Error", str(e))

    #  THEME + APPEARANCE

    def _toggle_theme(self):
        self.theme_name = "light" if self.theme_name == "dark" else "dark"
        self.T = THEMES[self.theme_name]
        self.theme_btn.config(
            text="☀️ Light" if self.theme_name == "dark" else "🌙 Dark"
        )
        self._apply_theme()

    def _apply_theme(self):
        T = self.T
        self.root.configure(bg=T["bg"])
        self.toolbar.configure(bg=T["toolbar_bg"])
        self.sidebar.configure(bg=T["sidebar_bg"])
        self.status_bar.configure(bg=T["status_bg"])
        self.status_label.configure(bg=T["status_bg"], fg=T["text_dim"])
        self.coord_label.configure(bg=T["status_bg"],  fg=T["text_dim"])

        for w in self.toolbar.winfo_children():
            try:
                w.configure(bg=T["toolbar_bg"], fg=T["btn_fg"],
                            activebackground=T["btn_active"],
                            activeforeground="#fff")
            except Exception:
                pass

        for w in self.sidebar.winfo_children():
            try:
                w.configure(bg=T["sidebar_bg"], fg=T["text"])
            except Exception:
                pass

        # Re-highlight active tool
        self._highlight_tool(self.tm.tool)
        self._update_color_preview()
        self._update_brush_preview()

        # canvas bg-color stays as user picked (not theme-driven)
        # but we can style the inner border
        for w in self.main_frame.winfo_children():
            try:
                w.configure(bg=T["bg"])
            except Exception:
                pass

    def _update_color_preview(self):
        self.color_preview.config(
            bg=self.T["sidebar_bg"],
            highlightbackground=self.T["border"]
        )
        self.color_preview.delete("all")
        c = self.tm.color
        self.color_preview.create_rectangle(
            4, 4, 116, 32, fill=c, outline=self.T["border"]
        )
        # show hex label with contrasting color
        r, g, b = int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)
        luma = 0.299*r + 0.587*g + 0.114*b
        text_color = "#000" if luma > 128 else "#fff"
        self.color_preview.create_text(60, 18, text=c.upper(),
                                       fill=text_color,
                                       font=("Consolas", 9, "bold"))

    def _update_brush_preview(self):
        s = min(self.tm.brush_size, 60)
        pad = 35
        self.brush_preview.config(
            bg=self.T["sidebar_bg"],
            width=70, height=70
        )
        self.brush_preview.delete("all")
        # background circle for contrast
        self.brush_preview.create_oval(
            2, 2, 68, 68,
            fill=self.T["btn_bg"], outline=self.T["border"]
        )
        half = s // 2
        cx, cy = 35, 35
        self.brush_preview.create_oval(
            cx - half, cy - half,
            cx + half, cy + half,
            fill=self.tm.color, outline=""
        )

    def _on_mouse_move(self, event):
        self.coord_label.config(text=f"X: {event.x}  Y: {event.y}")

    def _update_status(self):
        tool = self.tm.tool
        size = self.tm.brush_size
        clr  = self.tm.color
        self.status_label.config(
            text=f"  Tool: {tool}   |   Size: {size}px   |"
                 f"   Color: {clr.upper()}   |   "
                 f"Ctrl+Z Undo  •  Ctrl+S Save  •  Ctrl+N New"
        )
        self.root.after(500, self._update_status)

    # ════════════════════════════════════════════════════
    #  HELPERS
    # ════════════════════════════════════════════════════

    def _vsep(self, parent):
        """Vertical separator for toolbar."""
        tk.Frame(parent, width=1, bg=self.T["border"]).pack(
            side="left", fill="y", padx=4, pady=8
        )

    def run(self):
        self.root.mainloop()


# ═══════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    if not PIL_AVAILABLE:
        print("=" * 55)
        print("  ERROR: Pillow (PIL) is required!")
        print("  Run:   pip install Pillow")
        print("=" * 55)
    else:
        app = DrawingApp()
        app.run()
