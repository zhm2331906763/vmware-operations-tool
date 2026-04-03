import tkinter as tk
from tkinter import ttk

COLORS = {
    'primary': '#1976D2',
    'primary_light': '#42A5F5',
    'primary_dark': '#1565C0',
    'accent': '#4CAF50',
    'accent_light': '#81C784',
    'warning': '#FF9800',
    'danger': '#F44336',
    'bg_main': '#F5F5F5',
    'bg_card': '#FFFFFF',
    'bg_toolbar': '#FAFAFA',
    'text_primary': '#212121',
    'text_secondary': '#757575',
    'text_light': '#FFFFFF',
    'border': '#E0E0E0',
    'border_light': '#EEEEEE',
    'row_alt': '#FAFAFA',
    'row_selected': '#E3F2FD',
    'row_hover': '#F5F5F5',
    'success': '#4CAF50',
    'info': '#2196F3',
}

FONTS = {
    'normal': ('Microsoft YaHei', 10),
    'bold': ('Microsoft YaHei', 10, 'bold'),
    'title': ('Microsoft YaHei', 12, 'bold'),
    'small': ('Microsoft YaHei', 8),
    'button': ('Microsoft YaHei', 9),
}

PADDING = {
    'small': 2,
    'medium': 5,
    'large': 10,
}


def apply_theme(root):
    style = ttk.Style(root)
    style.theme_use('clam')

    style.configure('TFrame', background=COLORS['bg_main'])
    style.configure('Card.TFrame', background=COLORS['bg_card'])

    style.configure('TLabel',
                    background=COLORS['bg_main'],
                    foreground=COLORS['text_primary'],
                    font=FONTS['normal'])

    style.configure('Title.TLabel',
                    background=COLORS['bg_card'],
                    foreground=COLORS['text_primary'],
                    font=FONTS['title'])

    style.configure('Secondary.TLabel',
                    foreground=COLORS['text_secondary'],
                    font=FONTS['small'])

    style.configure('TButton',
                    font=FONTS['button'],
                    padding=PADDING['medium'])

    style.configure('Primary.TButton',
                    font=FONTS['button'],
                    background=COLORS['primary'],
                    foreground=COLORS['text_light'],
                    padding=PADDING['medium'])

    style.configure('Success.TButton',
                    font=FONTS['button'],
                    background=COLORS['success'],
                    foreground=COLORS['text_light'],
                    padding=PADDING['medium'])

    style.configure('Danger.TButton',
                    font=FONTS['button'],
                    background=COLORS['danger'],
                    foreground=COLORS['text_light'],
                    padding=PADDING['medium'])

    style.configure('TEntry',
                    font=FONTS['normal'],
                    fieldbackground=COLORS['bg_card'],
                    bordercolor=COLORS['border'])

    style.configure('TCombobox',
                    font=FONTS['normal'],
                    fieldbackground=COLORS['bg_card'])

    style.configure('Treeview',
                    font=FONTS['normal'],
                    rowheight=25,
                    background=COLORS['bg_card'],
                    foreground=COLORS['text_primary'],
                    fieldbackground=COLORS['bg_card'],
                    bordercolor=COLORS['border'])

    style.configure('Treeview.Heading',
                    font=FONTS['bold'],
                    background=COLORS['bg_toolbar'],
                    foreground=COLORS['text_primary'],
                    relief='flat',
                    bordercolor=COLORS['border'])

    style.map('Treeview',
              background=[('selected', COLORS['row_selected']),
                        ('hover', COLORS['row_hover'])])

    style.configure('TNotebook',
                    background=COLORS['bg_main'],
                    tabposition='n')

    style.configure('TNotebook.Tab',
                    font=FONTS['normal'],
                    padding=[10, 5],
                    background=COLORS['bg_toolbar'])

    style.map('TNotebook.Tab',
              background=[('selected', COLORS['bg_card'])],
              foreground=[('selected', COLORS['primary'])])

    style.configure('Vertical.TScrollbar',
                    background=COLORS['bg_toolbar'],
                    troughcolor=COLORS['bg_card'],
                    bordercolor=COLORS['border'])

    style.configure('Horizontal.TScrollbar',
                    background=COLORS['bg_toolbar'],
                    troughcolor=COLORS['bg_card'],
                    bordercolor=COLORS['border'])

    style.configure('Card.TLabelframe',
                    background=COLORS['bg_card'],
                    foreground=COLORS['text_primary'],
                    font=FONTS['title'],
                    bordercolor=COLORS['border'])

    style.configure('Card.TLabelframe.Label',
                    background=COLORS['bg_card'],
                    foreground=COLORS['text_primary'],
                    font=FONTS['title'])


def configure_widget_colors(widget):
    widget.configure(style='Card.TFrame')


TAB_ICONS = {
    'vCenter管理': '🔌',
    'ESXi主机巡检': '🖥️',
    '虚拟机巡检': '💻',
    '批量操作': '⚙️',
    '虚拟机克隆': '📦',
}

STATUS_ICONS = {
    'ready': '✅',
    'loading': '⏳',
    'success': '✅',
    'error': '❌',
    'warning': '⚠️',
}
