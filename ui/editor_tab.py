import customtkinter as ctk

class MarkdownEditorTab(ctk.CTkFrame):
    """A generic tab for Markdown content (Journal, Quests, etc.)"""
    def __init__(self, parent, default_text="# New Tab\n"):
        super().__init__(parent)
        self.filename = "" # Set dynamically later
        
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        
        # Toolbar
        self.toolbar = ctk.CTkFrame(self, height=30)
        self.toolbar.grid(row=0, column=0, sticky="ew", padx=5, pady=5)
        
        self.mode_btn = ctk.CTkButton(self.toolbar, text="👁️ Preview", width=80, height=24, command=self.toggle_view)
        self.mode_btn.pack(side="right", padx=5)

        # Editor
        self.editor = ctk.CTkTextbox(self, font=("Consolas", 14), wrap="word")
        self.editor.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)
        self.editor.insert("0.0", default_text)
        
        # Preview (Simple Textbox implementation)
        self.preview_box = ctk.CTkTextbox(self, font=("Consolas", 14), wrap="none", state="disabled")
        
        self.is_preview_active = False

    def get_text(self):
        return self.editor.get("0.0", "end")

    def set_text(self, text):
        self.editor.delete("0.0", "end")
        self.editor.insert("0.0", text)

    def toggle_view(self):
        if not self.is_preview_active:
             # Basic Preview (Raw text)
             raw_text = self.get_text()
             self.editor.grid_forget()
             
             self.preview_box.configure(state="normal")
             self.preview_box.delete("0.0", "end")
             self.preview_box.insert("0.0", raw_text)
             self.preview_box.configure(state="disabled")
             self.preview_box.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)
             
             self.mode_btn.configure(text="✏️ Edit")
             self.is_preview_active = True
        else:
             self.preview_box.grid_forget()
             self.editor.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)
             self.mode_btn.configure(text="👁️ Preview")
             self.is_preview_active = False