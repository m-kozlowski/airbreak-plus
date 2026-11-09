#ifndef _stubs_h_
#define _stubs_h_

// Addresses are defined in per-version s10_*_stubs.S files.

// draw something
extern void LCD_SetClipRectMax(void);
extern int GUI_SetColor(int color);
extern void GUI_DispStringAt(const char * s, unsigned short x, unsigned short y);
extern void LCD_DrawPixel(int x, int y);
extern const void * font_16;
extern void GUI_SetFont(const void * font);
extern void GUI_SetFont_default();
extern void GUI_SetTextMode(short param_1);
extern void GUI_SetTextAlign(short param_1);
extern void GUI_GotoXY(int x, int y);
extern void GUI_FillRect(int x, int y, int x1, int y1);
extern void LCD_FillRect(int x, int y, int x1, int y1);
extern int snprintf(char * buf, unsigned len, const char * fmt, ...);
extern unsigned char * gui_context;

extern unsigned tim_read_tim5(void);
extern float sqrtf(float value);

typedef unsigned size_t;

extern void * malloc(size_t __size);

#endif
