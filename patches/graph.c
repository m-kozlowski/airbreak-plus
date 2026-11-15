/* Graph rendering for the therapy-screen payload. */
#include "stubs.h"
#include "common_code.h"
#include "therapy_screen.h"

typedef struct {
	uint32 vtable;
	uint32 hwin;
	int position;
	int last_pos_x;
} graph_widget_t;

typedef int (*graph_draw_t)(graph_widget_t *obj);
typedef int (*graph_update_t)(graph_widget_t *obj, int new_position);
typedef void (*graph_header_update_t)(void *obj);
typedef void (*graph_numbers_update_t)(void *obj, int left_var, int right_var);

extern const uint32 graph_draw_original;
extern const uint32 graph_update_original;
extern const uint32 graph_header_update_original;
extern const uint32 graph_numbers_update_original;
extern const uint32 graph_simple_draw_original;
extern const uint32 graph_simple_update_original;
extern int gui_base_window_y0(void *obj);
extern int gui_base_window_height(void *obj);
extern void gui_invalidate_window(void *obj);
extern void gui_method_fc104_setup_and_invalidate(
	uint32 hwin, int left, int top, int right, int bottom);
extern void memcpy_unrolled(void *destination, const void *source,
			    unsigned size);

/* The stock constructor initializes the first 12 bytes after allocation. */
graph_widget_t *MAIN graph_widget_alloc(void) {
	graph_widget_t *obj = malloc(sizeof(*obj));
	if (obj)
		obj->last_pos_x = -1;
	return obj;
}

STATIC bool graph_enabled(void) {
	return therapy_screen_has_graph(therapy_screen_get_choice());
}

/* The native round gauge occupies the first 124 bytes. */
typedef struct {
	uint8 native[124];
	int last_pos_x, top;
} graph_simple_t;

graph_simple_t *MAIN graph_simple_alloc(void) {
	graph_simple_t *obj = malloc(sizeof(*obj));
	if (obj) { obj->last_pos_x = -1; obj->top = -1; }
	return obj;
}

/* The optional keep-screen-on patch registers this with keep_backlight. */
int MAIN graph_keep_backlight_requested(void) {
	return *therapy_mode != MODE_OFF && graph_enabled();
}

STATIC void LCD_FillRect2(int x1, int y1, int x2, int y2) {
	int temp = 0;
	if (y1 > y2) { temp = y2; y2 = y1; y1 = temp; }
	if (x1 > x2) { temp = x2; x2 = x1; x1 = temp; }
	LCD_FillRect(x1, y1, x2, y2);
}

STATIC void LCD_FillRect_Alt(int x, int y, int w, int h) {
	LCD_FillRect2(x, y, x+w-1, y+h-1);
}

// The parent also calls this draw method when only the numeric row is invalidated.
STATIC bool graph_widget_is_invalidated(void) {
	const short * const clip = (short*)(gui_context + 8);
	const short xOff = *(short*)(gui_context + 76);
	const short yOff = *(short*)(gui_context + 78);
	const int left = xOff + 0x39;
	const int top = yOff;
	const int right = xOff + 0xd5;
	const int bottom = yOff + 0x0e;

	return clip[0] <= right && clip[2] >= left &&
	       clip[1] <= bottom && clip[3] >= top;
}

STATIC bool fixed_string_changed(const uint8 *before, const uint8 *after,
				 unsigned size) {
	for (unsigned i = 0; i < size; i++) {
		if (before[i] != after[i])
			return true;
		if (before[i] == 0)
			return false;
	}
	return false;
}

STATIC bool bytes_changed(const uint8 *before, const uint8 *after,
			  unsigned size) {
	for (unsigned i = 0; i < size; i++) {
		if (before[i] != after[i])
			return true;
	}
	return false;
}

STATIC int graph_draw_column(int *last_pos_x, bool only_if_new, int top, int bottom) {
	// don't do anything if we are not in an active therapy mode
	if (*therapy_mode == 0) {
		*last_pos_x = -1;
		return 0;
	}

	const unsigned pos_x = (*pap_timer / 15) % 240; // ~6.66px per second (unit of timer is 10ms)
	if (only_if_new && *last_pos_x == (int)pos_x) return 0;
	*last_pos_x = pos_x;

	// Draw within the graph strip, outside the native widget's rectangle.
	unsigned * const color_ptr = (unsigned*)(gui_context + 60);
	short * const clip = (short*)(gui_context + 8);
	short * const xOff = (short*)(gui_context + 76);
	short * const yOff = (short*)(gui_context + 78);
	const short old_x0 = clip[0];
	const short old_y0 = clip[1];
	const short old_x1 = clip[2];
	const short old_y1 = clip[3];
	const short old_xOff = *xOff;
	const short old_yOff = *yOff;
	const unsigned old_color = *color_ptr;
	clip[0] = 0;
	clip[1] = top - 1;
	clip[2] = 239;
	clip[3] = bottom + 1;
	*xOff = 0;
	*yOff = 0;

	// Draw a strip chart
	const int height_pres = (bottom - top) / 2;
	const int height_flow = bottom - top - height_pres;

	int command = p_command * height_pres / 20.0f;
	int error = -p_error * height_pres * 0.15f;

	GUI_SetColor(0x000000);
	LCD_FillRect(pos_x, top - 1, pos_x + 11, bottom + 1);
	if (breath_progress > 0.0f && breath_progress <= 0.5f) { // Active inhale
		GUI_SetColor(0x101010);
		LCD_FillRect(pos_x, top - 1, pos_x + 1, bottom + 1);
	}

	float g_bottom = bottom;

	GUI_SetColor(0x202020);
	for(int i=1; i<=4; i++) { // draw 0, 5, 10, 15, 20 very faintly
		LCD_FillRect_Alt(pos_x, g_bottom - i*height_pres/4, 2, 1);
	}
	// draw amplified pressure error with respect to the commanded pressure
	GUI_SetColor(0x000080);
	LCD_FillRect2(pos_x, g_bottom - command, pos_x + 1, g_bottom - command + error);
	// draw the current commanded pressure
	GUI_SetColor(0x00FF88);
	LCD_FillRect_Alt(pos_x, g_bottom - command, 2, 1);

	float g_top = top;

	// Draw the leak-compensated flow variable as solid bars
	GUI_SetColor(0xFF8800);
	const int g_center = g_top + height_flow/2;
	LCD_FillRect2(pos_x, g_center, pos_x+1, g_center - clamp(*flow_compensated * height_flow / 80, -height_flow/2, height_flow/2));
	GUI_SetColor(0x000000);
	LCD_FillRect_Alt(pos_x, g_top + height_flow/2, 2, 1);

	GUI_SetColor(0x666666);
	LCD_FillRect_Alt(pos_x, top, 4, 1);
	LCD_FillRect_Alt(pos_x, top + height_flow, 4, 1);
	LCD_FillRect_Alt(pos_x, bottom, 4, 1);

	// restore the old clipping rectangle
	clip[0] = old_x0;
	clip[1] = old_y0;
	clip[2] = old_x1;
	clip[3] = old_y1;
	*xOff = old_xOff;
	*yOff = old_yOff;
	*color_ptr = old_color;

	return 1;
}

// Keep the pressure bar visible alongside the graph below it.
int MAIN graph_widget_draw(graph_widget_t *obj) {
	int result = ((graph_draw_t)graph_draw_original)(obj);
	if (!graph_enabled()) {
		obj->last_pos_x = -1;
		return result;
	}
	if (graph_widget_is_invalidated())
		graph_draw_column(&obj->last_pos_x, false, 155, 235);
	return result;
}

// The stock update method only redraws when the quantized bar position changes.
// Keep that invalidation and advance the graph independently on each new column.
int MAIN graph_widget_update(graph_widget_t *obj, int new_position) {
	int result = ((graph_update_t)graph_update_original)(obj, new_position);
	if (!graph_enabled()) {
		obj->last_pos_x = -1;
		return result;
	}
	graph_draw_column(&obj->last_pos_x, true, 155, 235);
	return result;
}

STATIC void graph_simple_column(graph_simple_t *obj, bool only_if_new) {
	if (!graph_enabled()) { obj->last_pos_x = -1; return; }
	/* Use the gap below the round gauge; leave the 41-pixel footer intact. */
	int top = gui_base_window_y0(obj) + gui_base_window_height(obj) + 1;
	if (top < 198) top = 198;
	if (top >= 276) return;
	if (top != obj->top) { obj->top = top; obj->last_pos_x = -1; }
	graph_draw_column(&obj->last_pos_x, only_if_new, top, 277);
}

void MAIN graph_simple_draw(graph_simple_t *obj) {
	((void (*)(void *))graph_simple_draw_original)(obj);
	graph_simple_column(obj, false);
}

void MAIN graph_simple_update(graph_simple_t *obj) {
	((void (*)(void *))graph_simple_update_original)(obj);
	graph_simple_column(obj, true);
}

/* The stock header updater invalidates on every raw MOP or PSP change, even
 * when one-decimal formatting produces the same visible text. Let it refresh
 * its caches and strings with invalidation suppressed, then invalidate only
 * when the rendered strings or widget status actually changed.
 */
void MAIN graph_header_update(void *obj) {
	uint8 *base = (uint8 *)obj;
	uint32 *hwin = (uint32 *)(base + 4);
	uint8 old_left[0x15];
	uint8 old_right[9];
	uint8 old_status[4];

	memcpy_unrolled(old_left, base + 0x90, sizeof(old_left));
	memcpy_unrolled(old_right, base + 0xa5, sizeof(old_right));
	memcpy_unrolled(old_status, base + 0x8c, sizeof(old_status));

	uint32 saved_hwin = *hwin;
	*hwin = 0;
	((graph_header_update_t)graph_header_update_original)(obj);
	*hwin = saved_hwin;

	if (fixed_string_changed(old_left, base + 0x90, sizeof(old_left)) ||
	    fixed_string_changed(old_right, base + 0xa5, sizeof(old_right)) ||
	    bytes_changed(old_status, base + 0x8c, sizeof(old_status)))
		gui_invalidate_window(obj);
}

/* The two pressure values use five-byte display buffers. Filter sub-display
 * raw changes after the stock formatter has updated those buffers.
 */
void MAIN graph_numbers_update(void *obj, int left_var, int right_var) {
	uint8 *base = (uint8 *)obj;
	uint32 *hwin = (uint32 *)(base + 4);
	uint8 old_left[5];
	uint8 old_right[5];

	memcpy_unrolled(old_left, base + 0x10, sizeof(old_left));
	memcpy_unrolled(old_right, base + 0x15, sizeof(old_right));

	uint32 saved_hwin = *hwin;
	*hwin = 0;
	((graph_numbers_update_t)graph_numbers_update_original)(
		obj, left_var, right_var);
	*hwin = saved_hwin;

	if (fixed_string_changed(old_left, base + 0x10, sizeof(old_left)) ||
	    fixed_string_changed(old_right, base + 0x15, sizeof(old_right)))
		gui_method_fc104_setup_and_invalidate(
			saved_hwin, 6, 0x19, 0xd6, 0x2d);
}
