/*
 * This replaces the normal pressure gauge code in the ROM.
 */
#include "stubs.h"
#include "common_code.h"

#define DRAW_PRESSURE 1
#define DRAW_FLOW 0

typedef struct {
	int last_pos_x;
} graph_state_t;

typedef int (*graph_draw_t)(int *obj);
typedef int (*graph_update_t)(int *obj, int new_position);
typedef void (*graph_header_update_t)(void *obj);
typedef void (*graph_numbers_update_t)(void *obj, int left_var, int right_var);

extern int variable_get_by_id(int var_id);
extern const unsigned short graph_enable_var_id;
extern const uint32 graph_draw_original;
extern const uint32 graph_update_original;
extern const uint32 graph_header_update_original;
extern const uint32 graph_numbers_update_original;
extern void gui_invalidate_window(void *obj);
extern void gui_method_fc104_setup_and_invalidate(
	uint32 hwin, int left, int top, int right, int bottom);
extern void memcpy_unrolled(void *destination, const void *source,
			    unsigned size);

STATIC void init_graph_state(graph_state_t *state) {
	state->last_pos_x = -1;
}

STATIC graph_state_t *get_graph_state(void) {
	return GET_PTR(PTR_GRAPH_DATA, graph_state_t, init_graph_state);
}

STATIC bool graph_enabled(void) {
	if (graph_enable_var_id == 0xffffu)
		return true;
	return variable_get_by_id(graph_enable_var_id) != 0;
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

STATIC int graph_draw_current_column(bool only_if_new) {
	graph_state_t *state = get_graph_state();

	// don't do anything if we are not in an active therapy mode
	if (*therapy_mode == 0) {
		state->last_pos_x = -1;
		return 0;
	}

	const unsigned pos_x = (*pap_timer / 15) % 240; // ~6.66px per second (unit of timer is 10ms)
	if (only_if_new && state->last_pos_x == (int)pos_x) return 0;
	state->last_pos_x = pos_x;

	// break out of the current clipping so we can drawon the entire screen
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
	clip[1] = 0;
	clip[2] = 0x1000;
	clip[3] = 0x1000;
	*xOff = 0;
	*yOff = 0;

	// Draw a strip chart
	const int width = 240;
	const int top = 155; // 150--230
	const int bottom = 235;
	const int height = bottom - top;

	#define HEIGHT_PRES 40
	#define HEIGHT_FLOW 40

	int command = p_command * 2.0f;
	int error = -p_error * 6.0f;

	GUI_SetColor(0x000000);
	LCD_FillRect(pos_x, top - 1, pos_x + 11, bottom + 1);
	if (breath_progress > 0.0f && breath_progress <= 0.5f) { // Active inhale
		GUI_SetColor(0x101010);
		LCD_FillRect(pos_x, top - 1, pos_x + 1, bottom + 1);
	}

	float g_top = top + HEIGHT_FLOW;
	float g_bottom = top + HEIGHT_FLOW + HEIGHT_PRES;

	#if HEIGHT_PRES > 0
		GUI_SetColor(0x202020);
		for(int i=1; i<=4; i++) { // draw 0, 5, 10, 15, 20 very faintly
			LCD_FillRect_Alt(pos_x, g_bottom - i*10, 2, 1);
		}
		// draw amplified pressure error with respect to the commanded pressure
		GUI_SetColor(0x000080);
		LCD_FillRect2(pos_x, g_bottom - command, pos_x + 1, g_bottom - command + error);
		// draw the current commanded pressure
		GUI_SetColor(0x00FF88);
		LCD_FillRect_Alt(pos_x, g_bottom - command, 2, 1);
	#endif

	g_top = top;
	g_bottom = top + HEIGHT_FLOW;

	#if HEIGHT_FLOW > 0
		// Draw the leak-compensated flow variable as solid bars
		GUI_SetColor(0xFF8800);
		const int g_center = g_top + HEIGHT_FLOW/2;
		LCD_FillRect2(pos_x, g_center, pos_x+1, g_center - clamp(*flow_compensated / 2, -HEIGHT_FLOW/2, HEIGHT_FLOW/2));
		GUI_SetColor(0x000000);
		LCD_FillRect_Alt(pos_x, g_top + HEIGHT_FLOW/2, 2, 1);
	#endif

	GUI_SetColor(0x666666);
	LCD_FillRect_Alt(pos_x, top, 4, 1);
	LCD_FillRect_Alt(pos_x, top + HEIGHT_FLOW, 4, 1);
	LCD_FillRect_Alt(pos_x, top + HEIGHT_FLOW + HEIGHT_PRES, 4, 1);

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

// Replaces the stock bar draw method.
int MAIN start(int *obj) {
	if (!graph_enabled()) {
		get_graph_state()->last_pos_x = -1;
		return ((graph_draw_t)graph_draw_original)(obj);
	}
	if (!graph_widget_is_invalidated()) return 0;
	return graph_draw_current_column(false);
}

// The stock update method only redraws when the quantized bar position changes.
// Preserve its state, but drive the time-based graph directly on each new column.
int MAIN graph_widget_update(int *obj, int new_position) {
	if (!graph_enabled()) {
		get_graph_state()->last_pos_x = -1;
		return ((graph_update_t)graph_update_original)(obj, new_position);
	}
	obj[2] = new_position;
	return graph_draw_current_column(true);
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


// Causes the device to crash and reboot
/*
#if 0
	GUI_SetColor(0x8);
	GUI_FillRect(0, 130, 200, 160);

	GUI_SetColor(0xFF0000);
	GUI_SetFont(font_16); // Causes device to crash and reboot
	//static const char __attribute__((__section__(".text"))) msg[] = "Hello, world!";
	//static const char __attribute__((__section__(".text"))) fmt[] = "%d.%02d";
	GUI_DispStringAt("Hello, world", 10, 130);
	char buf[16];
	int flow = fvars[1] * 100;
	snprintf(buf, sizeof(buf), "%d.%02d", flow / 100, flow % 100);
	GUI_SetColor(0x00FF00);
	GUI_DispStringAt(buf, 40, 150);
#endif

// Also tried:
GUI_SetColor(0xFFFF00);
GUI_SetTextMode(2);
GUI_SetTextAlign(0);
GUI_SetFont_default();
GUI_DispStringAt("Hello, world", 20, top + HEIGHT_FLOW + 20);
// No luck, displays nothing. Changing params of GUI_DispStringAt to short or unsigned short does nothing too.

*/
