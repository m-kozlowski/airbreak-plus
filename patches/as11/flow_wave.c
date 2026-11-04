/* Flow therapy view: screen-owned history, sampled before the LCD sleep gate. */

#include "stubs.h"
#include "vars.h"

#define HISTORY_MS       12000u
#define SAMPLE_MS           40u
#define PAINT_MS           120u
#define SAMPLE_COUNT      300u
#define BUFFER_COUNT      SAMPLE_COUNT
#define PLOT_WIDTH        320u
#define PLOT_LEFT          22
#define PLOT_RIGHT_MARGIN  19
#define TRACE_COLUMNS     (PLOT_WIDTH - PLOT_LEFT - PLOT_RIGHT_MARGIN + 1)
#define STATISTICS_TOP     81
#define STATISTICS_HEIGHT 119
#define PLOT_ROW_HEIGHT    65
#define MAX_JOIN_MS      1000u
#define PLOT_STRIDE       (PLOT_WIDTH * 2u)
#define BAND_HEIGHT         1u
#define FLOW_LIMIT         500  /* 60 L/min, in raw units of 1/500 L/s. */
#define PRESSURE_LIMIT    1500  /* 30 cmH2O, in raw units of 1/50 cmH2O. */
#define TSS_FLOW_WAVE        2
#define FG_STATE_THERAPY     3

/* Native page indexes and localized statistic labels differ between releases. */
#if defined(APPX_VER_8_6_0)
#define GUI_VERSION_VALUE(v86, v87) v86
#elif defined(APPX_VER_8_7_0) || defined(APPX_VER_8_8_0)
#define GUI_VERSION_VALUE(v86, v87) v87
#else
#error Flow GUI layout is not defined for this APPX
#endif

enum {
    PAGE_SIMPLE = GUI_VERSION_VALUE(2, 3),
    PAGE_COUNT = GUI_VERSION_VALUE(67, 68),
    TEXT_CELSIUS = GUI_VERSION_VALUE(0x42, 0x43),
    TEXT_FAHRENHEIT = GUI_VERSION_VALUE(0x43, 0x44),
    TEXT_MINUTES = GUI_VERSION_VALUE(0x44, 0x45),
    TEXT_PERCENT = GUI_VERSION_VALUE(0x45, 0x46),
    TEXT_EPAP = GUI_VERSION_VALUE(0x47, 0x48),
    TEXT_HUMIDITY = GUI_VERSION_VALUE(0x48, 0x49),
    TEXT_IPAP = GUI_VERSION_VALUE(0x49, 0x4A),
    TEXT_IE = GUI_VERSION_VALUE(0x4D, 0x4E),
    TEXT_LEAK = GUI_VERSION_VALUE(0x4E, 0x4F),
    TEXT_MAX_IPAP = GUI_VERSION_VALUE(0x4F, 0x50),
    TEXT_MIN_EPAP = GUI_VERSION_VALUE(0x50, 0x51),
    TEXT_MODE = GUI_VERSION_VALUE(0x51, 0x52),
    TEXT_MV = GUI_VERSION_VALUE(0x52, 0x53),
    TEXT_PRESSURE = GUI_VERSION_VALUE(0x54, 0x55),
    TEXT_PS = GUI_VERSION_VALUE(0x55, 0x56),
    TEXT_RAMP = GUI_VERSION_VALUE(0x57, 0x58),
    TEXT_RR = GUI_VERSION_VALUE(0x59, 0x5A),
    TEXT_SPONT_CYCLE = GUI_VERSION_VALUE(0x5B, 0x5C),
    TEXT_SPONT_TRIGGER = GUI_VERSION_VALUE(0x5C, 0x5D),
    TEXT_TGMV = GUI_VERSION_VALUE(0x5F, 0x60),
    TEXT_TI = GUI_VERSION_VALUE(0x61, 0x62),
    TEXT_TI_RANGE = GUI_VERSION_VALUE(0x65, 0x66),
    TEXT_TUBE_TEMP = GUI_VERSION_VALUE(0x66, 0x67),
    TEXT_VT = GUI_VERSION_VALUE(0x68, 0x69),
    TEXT_EMPTY = GUI_VERSION_VALUE(0x6A, 0x6B),
    TEXT_NONE = GUI_VERSION_VALUE(0x210, 0x213), /* One past the text table. */
};
#undef GUI_VERSION_VALUE

enum {
    COLOR_BLACK, COLOR_FLOW, COLOR_PRESSURE, COLOR_GRID, COLOR_ZERO, COLOR_TEXT,
};

/* RGB565 lets the native LCD driver send rows instead of individual pixels. */
static const unsigned short plot_colors[] = {
    0, 0x067Cu, 0xFDA8u, 0x3186u, 0x9492u, 0xFFFFu,
};

typedef struct {
    unsigned int time;
    short flow;
    short pressure;
} flow_sample_t;

typedef struct {
    int left, top, right, bottom;
} plot_rect_t;

typedef struct {
    int top;
    unsigned short pixels[PLOT_WIDTH * BAND_HEIGHT];
} plot_band_t;

typedef struct {
    unsigned char low, high;
} plot_span_t;

typedef struct {
    plot_span_t flow, pressure;
} plot_column_t;

typedef struct {
    unsigned int head;
    unsigned int count;
    unsigned int last_paint;
    unsigned int epoch;
    plot_rect_t frame_rect;
    flow_sample_t samples[BUFFER_COUNT];
    /* Painters never read the live ring: animation can repaint just one child. */
    plot_column_t columns[TRACE_COLUMNS];
    unsigned int frame_samples;
    int frame_pressure;
    plot_band_t band;
} flow_history_t;

typedef struct flow_screen flow_screen_t;

typedef struct {
    unsigned char native[0x0c]; /* Native therapy-list item. */
    flow_screen_t *screen;
    void *vtable[27];
} flow_plot_t;

struct flow_screen {
    unsigned char native[0x30]; /* Common therapy page, not SinglePressure. */
    void *vtable[21];
    void (*native_paint)(void *);
    flow_plot_t plot;
    unsigned char scroller[0x4c];
    unsigned char scrollbar[0x20];
    unsigned int scroll_state[2][2];
    void *items[9];
    void *rows[33];
    unsigned char action[0x10];
    flow_history_t history;
};

/* The patcher resolves the reclaimed page and the native TSS switch. */
typedef struct {
    void *tss_switch;
    unsigned int page_index;
} flow_layout_t;

volatile const flow_layout_t flow_layout __attribute__((used, section(".rodata.params"))) = {0};

int flow_wave_is_therapy_page(const unsigned char *page)
{
    return *page == flow_layout.page_index || GuiMenuCentre_is_therapy_page(page);
}

typedef struct {
    unsigned char native[0x24];
    void **items;
    unsigned int count;
} flow_scroller_t;

typedef struct {
    unsigned int current;
    void *pages[PAGE_COUNT];
} flow_menu_centre_t;

typedef struct {
    void *native;
    flow_menu_centre_t *menu;
} flow_gui_context_t;

/* Small numeric glyphs keep axis labels legible without consuming the plot.
 * Each byte is one five-pixel row; the pressure readout uses 2x glyphs. */
static const unsigned char digits[][7] = {
    {14,17,19,21,25,17,14}, {4,12,4,4,4,4,14},
    {14,17,1,2,4,8,31}, {30,1,1,14,1,1,30},
    {2,6,10,18,31,2,2}, {31,16,16,30,1,1,30},
    {14,16,16,30,17,17,14}, {31,1,2,4,8,8,8},
    {14,17,17,14,17,17,14}, {14,17,17,15,1,1,14},
    {0,0,0,31,0,0,0}, {0,0,0,0,0,6,6}, {0,0,15,16,14,1,30},
};

static int clamp(int value, int low, int high)
{
    return value < low ? low : value > high ? high : value;
}

static void plot_pixel(plot_band_t *band, int x, int y, unsigned int color)
{
    y -= band->top;
    if ((unsigned int)x >= PLOT_WIDTH || (unsigned int)y >= BAND_HEIGHT)
        return;
    band->pixels[y * PLOT_WIDTH + x] = plot_colors[color];
}

static void raster_trace(flow_history_t *history, int x0, int y0, int x1, int y1, int pressure)
{
    /* Time never runs backwards within a trace. Its pixels in each column
     * form one vertical span, including shared endpoints and repeated x.
     * Capture gaps start separate traces, more than one column apart. */
    int dx = x1 > x0 ? x1 - x0 : x0 - x1;
    int dy = y1 > y0 ? y0 - y1 : y1 - y0;
    int sx = x0 < x1 ? 1 : -1;
    int sy = y0 < y1 ? 1 : -1;
    int error = dx + dy;
    for (;;) {
        plot_column_t *column = &history->columns[x0 - history->frame_rect.left];
        plot_span_t *span = pressure ? &column->pressure : &column->flow;
        if (y0 < span->low) span->low = (unsigned char)y0;
        if (y0 > span->high) span->high = (unsigned char)y0;
        if (x0 == x1 && y0 == y1)
            return;
        int twice_error = 2 * error;
        if (twice_error >= dy) { error += dy; x0 += sx; }
        if (twice_error <= dx) { error += dx; y0 += sy; }
    }
}

static void small_text(plot_band_t *band, int x, int y, const char *text, int scale, unsigned int color)
{
    int row = band->top - y;
    if (row < 0 || row >= 7 * scale)
        return;
    row /= scale;
    for (; *text; ++text, x += 6 * scale) {
        unsigned int glyph;
        if (*text >= '0' && *text <= '9')
            glyph = (unsigned int)(*text - '0');
        else if (*text == '-')
            glyph = 10;
        else if (*text == '.')
            glyph = 11;
        else if (*text == 's')
            glyph = 12;
        else
            continue;
        for (int col = 0; col < 5; ++col) {
            if ((digits[glyph][row] & (16u >> col)) == 0)
                continue;
            for (int dx = 0; dx < scale; ++dx)
                plot_pixel(band, x + col * scale + dx, band->top, color);
        }
    }
}

static plot_rect_t plot_rect(flow_screen_t *screen)
{
    plot_rect_t rect;
    rect.left = PLOT_LEFT;
    rect.right = gui_widget_width(screen) - gui_widget_width(screen->scrollbar) - PLOT_RIGHT_MARGIN;
    rect.top = 5;
    /* The fixed upper area and the first scroller row form one plot. When
     * that row scrolls away, the graph fits above the statistics instead. */
    int bottom = STATISTICS_TOP;
    if (gui_widget_is_visible(&screen->plot))
        bottom = clamp(gui_widget_y(&screen->plot) - gui_widget_y(screen) + PLOT_ROW_HEIGHT,
            STATISTICS_TOP, STATISTICS_TOP + PLOT_ROW_HEIGHT);
    rect.bottom = bottom - 15;
    return rect;
}

static void draw_axes(plot_band_t *band, plot_rect_t rect)
{
    int width = rect.right - rect.left;
    int height = rect.bottom - rect.top;
    int zero = rect.top + height / 2;
    int y = band->top;
    if (y >= rect.top && y <= rect.bottom && (y - rect.top) % 5 == 0) {
        for (int i = 0; i <= 6; ++i)
            band->pixels[rect.left + i * width / 6] = plot_colors[COLOR_GRID];
    }
    for (int i = 0; i <= 4; ++i) {
        if (y == rect.top + i * height / 4)
            for (int x = rect.left; x <= rect.right; x += 5)
                band->pixels[x] = plot_colors[COLOR_GRID];
    }
    if (y == zero)
        for (int x = rect.left; x <= rect.right; ++x)
            band->pixels[x] = plot_colors[COLOR_ZERO];
    /* Intermediate scale ticks: 30 L/min on the left, 5 cmH2O on the right. */
    for (int i = 1; i < 4; ++i)
        if (y == rect.top + i * height / 4)
            for (int x = rect.left - 4; x < rect.left; ++x)
                band->pixels[x] = plot_colors[COLOR_FLOW];
    for (int i = 1; i < 6; ++i)
        if (y == rect.bottom - i * height / 6)
            for (int x = rect.right + 1; x <= rect.right + 4; ++x)
                band->pixels[x] = plot_colors[COLOR_PRESSURE];
    small_text(band, rect.left - 18, rect.top, "60", 1, COLOR_FLOW);
    small_text(band, rect.left - 12, zero - 3, "0", 1, COLOR_FLOW);
    small_text(band, rect.left - 22, rect.bottom - 6, "-60", 1, COLOR_FLOW);
    small_text(band, rect.right + 5, rect.top, "30", 1, COLOR_PRESSURE);
    small_text(band, rect.right + 5, rect.bottom - 6, "0", 1, COLOR_PRESSURE);
    small_text(band, rect.left - 9, rect.bottom + 4, "-12s", 1, COLOR_TEXT);
    small_text(band, rect.left + width / 3 - 6, rect.bottom + 4, "-8", 1, COLOR_TEXT);
    small_text(band, rect.left + width * 2 / 3 - 6, rect.bottom + 4, "-4", 1, COLOR_TEXT);
    small_text(band, rect.right - 4, rect.bottom + 4, "0", 1, COLOR_TEXT);
}

static int sample_y(plot_rect_t rect, int raw, int pressure)
{
    int height = rect.bottom - rect.top;
    if (pressure)
        return rect.bottom - clamp(raw, 0, PRESSURE_LIMIT) * height / PRESSURE_LIMIT;
    return rect.top + (FLOW_LIMIT - clamp(raw, -FLOW_LIMIT, FLOW_LIMIT)) * height / (2 * FLOW_LIMIT);
}

static unsigned int time_pixel(unsigned int elapsed, unsigned int width)
{
    /* Split the product to avoid overflow without a 64-bit division helper. */
    return elapsed / HISTORY_MS * width + elapsed % HISTORY_MS * width / HISTORY_MS;
}

static void prepare_frame(flow_history_t *history, unsigned int now)
{
    plot_rect_t rect = history->frame_rect;
    unsigned int index = (history->head + BUFFER_COUNT - history->count) % BUFFER_COUNT;
    unsigned int width = (unsigned int)(rect.right - rect.left);
    unsigned int elapsed = now - history->epoch;
    unsigned int scroll = time_pixel(elapsed, width);
    unsigned int previous_time = 0;
    int previous_x = 0, previous_flow = 0, previous_pressure = 0;
    /* Rasterize once per frame, replacing projected points with column spans.
     * Empty spans have low > high; painters only test the current scanline. */
    for (unsigned int x = 0; x <= width; ++x)
        history->columns[x] = (plot_column_t){{255, 0}, {255, 0}};
    history->frame_samples = 0;
    for (unsigned int i = 0; i < history->count; ++i) {
        const flow_sample_t *sample = &history->samples[index];
        unsigned int age = elapsed - sample->time;
        if (age <= HISTORY_MS) {
            int x = rect.right - (int)(scroll - time_pixel(sample->time, width));
            int flow = sample_y(rect, sample->flow, 0);
            int pressure = sample_y(rect, sample->pressure, 1);
            if (!history->frame_samples || sample->time - previous_time > MAX_JOIN_MS) {
                previous_x = x;
                previous_flow = flow;
                previous_pressure = pressure;
            }
            raster_trace(history, previous_x, previous_flow, x, flow, 0);
            raster_trace(history, previous_x, previous_pressure, x, pressure, 1);
            ++history->frame_samples;
            history->frame_pressure = sample->pressure;
            previous_time = sample->time;
            previous_x = x;
            previous_flow = flow;
            previous_pressure = pressure;
        }
        index = (index + 1) % BUFFER_COUNT;
    }
}

static void draw_traces(flow_history_t *history)
{
    int y = history->band.top;
    plot_rect_t rect = history->frame_rect;
    if (!history->frame_samples || y < rect.top || y > rect.bottom)
        return;
    for (int x = rect.left; x <= rect.right; ++x) {
        const plot_column_t *column = &history->columns[x - rect.left];
        if (y >= column->flow.low && y <= column->flow.high)
            history->band.pixels[x] = plot_colors[COLOR_FLOW];
        if (y >= column->pressure.low && y <= column->pressure.high)
            history->band.pixels[x] = plot_colors[COLOR_PRESSURE];
    }
}

static void draw_pressure(flow_history_t *history, plot_rect_t rect)
{
    char text[5];
    int raw, tenths, n = 0;
    int y = history->band.top;
    if (!history->frame_samples || y < rect.top + 2 || y > rect.top + 17)
        return;
    raw = history->frame_pressure;
    tenths = (clamp(raw, 0, 2000) + 2) / 5;
    if (tenths >= 100)
        text[n++] = (char)('0' + tenths / 100);
    text[n++] = (char)('0' + tenths / 10 % 10);
    text[n++] = '.';
    text[n++] = (char)('0' + tenths % 10);
    text[n] = 0;
    /* Cover only old history at the left, leaving incoming samples unobscured. */
    for (int x = rect.left + 2; x <= rect.left + 3 + n * 12; ++x)
        history->band.pixels[x] = plot_colors[COLOR_BLACK];
    small_text(&history->band, rect.left + 4, rect.top + 3, text, 2, COLOR_PRESSURE);
}

static void render_plot(flow_history_t *history)
{
    plot_rect_t rect = history->frame_rect;
    memset(history->band.pixels, 0, sizeof(history->band.pixels));
    if (rect.bottom - rect.top < 24 || history->band.top > rect.bottom + 12 ||
            history->band.top + (int)BAND_HEIGHT <= rect.top)
        return;
    draw_axes(&history->band, rect);
    draw_traces(history);
    draw_pressure(history, rect);
}

static void paint_plot_region(flow_screen_t *screen, int offset, int height)
{
    flow_history_t *history = &screen->history;
    gui_render_context_t context;
    gui_render_context_snapshot(&context);
    /* Native paint is called once per visible clip, not once per widget.
     * Rasterize only its rows; the bitmap driver clips columns itself. */
    int top = clamp(context.clip_top - context.origin_y, 0, height);
    int bottom = clamp(context.clip_bottom + 1 - context.origin_y, 0, height);
    gui_bitmap_t bitmap = {
        PLOT_WIDTH, BAND_HEIGHT, PLOT_STRIDE, 16, (const unsigned char *)history->band.pixels, 0, 0,
    };
    for (; top < bottom; top += BAND_HEIGHT) {
        history->band.top = top + offset;
        render_plot(history);
        bitmap.height = (unsigned short)clamp(bottom - top, 0, BAND_HEIGHT);
        gui_paint_draw_bitmap(&bitmap, 0, top);
    }
}

static void flow_plot_paint(flow_plot_t *widget)
{
    /* Both painters use page coordinates and the same prepared frame, even
     * when a scroll-animation tick repaints only the moving child. */
    paint_plot_region(widget->screen, gui_widget_y(widget) - gui_widget_y(widget->screen), PLOT_ROW_HEIGHT);
}

static void flow_page_paint(flow_screen_t *screen)
{
    screen->native_paint(screen);
    paint_plot_region(screen, 0, STATISTICS_TOP);
}

static void sample_history(flow_screen_t *screen, unsigned int now)
{
    flow_history_t *history = &screen->history;
    if (DataItem_read_value_by_id(VAR_ID_TSS) != TSS_FLOW_WAVE ||
            DataItem_read_value_by_id(VAR_ID_ZRM) != FG_STATE_THERAPY) {
        history->count = 0;
        return;
    }
    if (history->count) {
        unsigned int previous = history->samples[(history->head + BUFFER_COUNT - 1) % BUFFER_COUNT].time;
        unsigned int elapsed = now - history->epoch;
        if (elapsed >= previous && elapsed - previous < SAMPLE_MS)
            return;
        /* A delayed GUI pass leaves a gap, not an empty history. */
        if (elapsed < previous)
            history->count = 0;
    }
    if (!history->count) {
        history->epoch = now;
        history->last_paint = now - PAINT_MS;
    }
    flow_sample_t *sample = &history->samples[history->head];
    sample->time = now - history->epoch;
    sample->flow = (short)DataItem_read_value_by_id(VAR_ID_RFL);
    sample->pressure = (short)DataItem_read_value_by_id(VAR_ID_MKP);
    history->head = (history->head + 1) % BUFFER_COUNT;
    if (history->count < SAMPLE_COUNT)
        ++history->count;
}

void flow_wave_update_gui(flow_gui_context_t *context)
{
    user_interface_update_gui_state_and_cache(context);
    flow_screen_t *screen = context->menu->pages[flow_layout.page_index];
    if (!screen)
        return;
    unsigned int now = gui_time_milliseconds();
    flow_history_t *history = &screen->history;
    /* This call precedes the LCD gate. Capture continues while asleep, but
     * frame publication happens at most once per outer UI pass, never from
     * a timer inside the native paint drain. Touch processing gets its turn. */
    sample_history(screen, now);
    if (!gui_widget_is_visible(screen) || now - history->last_paint < PAINT_MS)
        return;
    history->frame_rect = plot_rect(screen);
    history->last_paint = now;
    prepare_frame(history, now);
    /* Invalidating the page does not invalidate its child windows. */
    gui_widget_invalidate_rect(screen, 0, 0, PLOT_WIDTH - 1, STATISTICS_TOP - 1);
    if (gui_widget_is_visible(&screen->plot))
        gui_widget_invalidate_rect(&screen->plot, 0, 0, PLOT_WIDTH - 1, PLOT_ROW_HEIGHT - 1);
}

enum { ROW_VALUE, ROW_PAIR, ROW_ADAPTER };
typedef struct {
    unsigned short first, second, label, unit;
    unsigned char kind;
    signed char scale;
} row_definition_t;

/* Therapy statistics, in the native group order. Each row retains its
 * native DataItem availability rules and formatting; only ownership changes.
 * GUI text IDs are the stock labels, while variable IDs come from vars.h. */
static const row_definition_t row_definitions[] = {
    {VAR_ID_TOM, 0, TEXT_MODE, TEXT_NONE, ROW_VALUE, 0},
    {VAR_ID_XE1, 0, TEXT_MAX_IPAP, TEXT_NONE, ROW_VALUE, 0},
    {VAR_ID_ZZ1, 0, TEXT_IPAP, TEXT_NONE, ROW_VALUE, 0},
    {VAR_ID_XA1, 0, TEXT_IPAP, TEXT_NONE, ROW_VALUE, 0},
    {VAR_ID_XB1, 0, TEXT_IPAP, TEXT_NONE, ROW_VALUE, 0},
    {VAR_ID_XE2, 0, TEXT_MIN_EPAP, TEXT_NONE, ROW_VALUE, 0},
    {VAR_ID_ZZ2, 0, TEXT_EPAP, TEXT_NONE, ROW_VALUE, 0},
    {VAR_ID_XA2, 0, TEXT_EPAP, TEXT_NONE, ROW_VALUE, 0},
    {VAR_ID_XB2, 0, TEXT_EPAP, TEXT_NONE, ROW_VALUE, 0},
    {VAR_ID_XC1, 0, TEXT_EPAP, TEXT_NONE, ROW_VALUE, 0},
    {VAR_ID_XD2, VAR_ID_XD1, TEXT_EPAP, 0, ROW_PAIR, 0},
    {VAR_ID_XE3, 0, TEXT_PS, TEXT_NONE, ROW_VALUE, 0},
    {VAR_ID_ZZ2, VAR_ID_ZZ1, TEXT_PS, 0, ROW_PAIR, 10},
    {VAR_ID_XA2, VAR_ID_XA1, TEXT_PS, 0, ROW_PAIR, 10},
    {VAR_ID_XB2, VAR_ID_XB1, TEXT_PS, 0, ROW_PAIR, 10},
    {VAR_ID_XC3, VAR_ID_XC2, TEXT_PS, 0, ROW_PAIR, 0},
    {VAR_ID_XD4, VAR_ID_XD3, TEXT_PS, 0, ROW_PAIR, 0},
    {VAR_ID_GRM, VAR_ID_RMT, TEXT_RAMP, TEXT_MINUTES, ROW_ADAPTER, 0},
    {VAR_ID_GHM, VAR_ID_HMS, TEXT_HUMIDITY, TEXT_NONE, ROW_ADAPTER, 0},
    {VAR_ID_GMH, VAR_ID_GTC, TEXT_TUBE_TEMP, TEXT_CELSIUS, ROW_ADAPTER, 0},
    {VAR_ID_GMH, VAR_ID_GTF, TEXT_TUBE_TEMP, TEXT_FAHRENHEIT, ROW_ADAPTER, 0},
    {VAR_ID_ZLF, 0, TEXT_LEAK, TEXT_NONE, ROW_VALUE, 0},
    {VAR_ID_MV5, 0, TEXT_MV, TEXT_NONE, ROW_VALUE, 0},
    {VAR_ID_RRR, 0, TEXT_RR, TEXT_NONE, ROW_VALUE, 0},
    {VAR_ID_ZTD, 0, TEXT_VT, TEXT_NONE, ROW_VALUE, 0},
    {VAR_ID_XE5, VAR_ID_XE4, TEXT_TI_RANGE, 0, ROW_PAIR, 0},
    {VAR_ID_ZZ8, VAR_ID_ZZ7, TEXT_TI_RANGE, 0, ROW_PAIR, 0},
    {VAR_ID_XA8, VAR_ID_XA7, TEXT_TI_RANGE, 0, ROW_PAIR, 0},
    {VAR_ID_IER, 0, TEXT_IE, TEXT_NONE, ROW_VALUE, 1},
    {VAR_ID_IN5, 0, TEXT_TI, TEXT_NONE, ROW_VALUE, 0},
    {VAR_ID_TGT, 0, TEXT_TGMV, TEXT_NONE, ROW_VALUE, 0},
    {VAR_ID_RTR, 0, TEXT_SPONT_TRIGGER, TEXT_PERCENT, ROW_VALUE, 9},
    {VAR_ID_RCR, 0, TEXT_SPONT_CYCLE, TEXT_PERCENT, ROW_VALUE, 9},
};

static void build_statistics(flow_screen_t *screen, void *controller)
{
    static const unsigned short summaries[][2] = {
        {VAR_ID_IPC, 0x7fff}, {VAR_ID_MPI, VAR_ID_MPA}, {VAR_ID_HMI, VAR_ID_HMA},
    };
    static const unsigned char group_counts[] = {17, 4, 4, 6, 2};
    for (unsigned int i = 0; i < 3; ++i)
        screen->items[i + 1] = GuiTherapySummaryRow_ctor(heap_alloc(0x28), 65,
            summaries[i][0], summaries[i][1], TEXT_PRESSURE);

    for (unsigned int i = 0; i < 33; ++i) {
        const row_definition_t *row = &row_definitions[i];
        if (row->kind == ROW_PAIR) {
            screen->rows[i] = GuiTherapyPairRow_ctor(heap_alloc(0x38), row->first,
                row->second, row->label, TEXT_EMPTY, TEXT_EMPTY, TEXT_EMPTY, TEXT_NONE, row->scale, -1, controller);
        } else if (row->kind == ROW_ADAPTER) {
            void *adapter = GuiTherapyDoubleNodeAdapter_ctor(heap_alloc(0x48), row->first, 1, row->second);
            screen->rows[i] = GuiTherapyAdapterRow_ctor(heap_alloc(0x34), adapter, row->label, row->unit);
        } else {
            screen->rows[i] = GuiTherapyValueRow_ctor(heap_alloc(0x18), row->first, row->label, row->unit, row->scale);
        }
    }
    unsigned int first = 0;
    for (unsigned int i = 0; i < 5; ++i) {
        screen->items[i + 4] = GuiTherapyRowGroup_ctor(heap_alloc(0x20), screen->rows + first, group_counts[i], 2);
        first += group_counts[i];
    }
}

static void flow_page_update(flow_screen_t *screen)
{
    GuiScroller_update_items(screen->scroller);
}

static void flow_page_timer(void *screen, void *timer)
{
    /* The common constructor creates a timer. Let it expire without rearming;
     * the outer UI poll owns frame cadence, including capture while asleep. */
    (void)screen;
    (void)timer;
}

void __attribute__((section(".text.0.main"))) start(flow_menu_centre_t *menu, void *root)
{
    flow_screen_t *screen = heap_alloc(sizeof(*screen));
    menu->pages[flow_layout.page_index] = screen;
    if (!screen)
        return;
    memset(screen, 0, sizeof(*screen));

    /* Only the value controller is shared, as in the stock construction.
     * Windows, rows, adapters, arrays and scroll states belong to this page. */
    flow_scroller_t *stock = *(void **)((unsigned char *)menu->pages[PAGE_SIMPLE] + 0x18);
    void **pressure_rows = *(void ***)((unsigned char *)stock->items[4] + 0x0c);
    void *controller = *(void **)((unsigned char *)pressure_rows[10] + 0x34);
    build_statistics(screen, controller);

    GuiTherapyListItem_ctor(&screen->plot, PLOT_ROW_HEIGHT);
    screen->plot.screen = screen;
    void **vtable = *(void ***)&screen->plot;
    for (unsigned int i = 0; i < 27; ++i)
        screen->plot.vtable[i] = vtable[i];
    screen->plot.vtable[0x0c / 4] = flow_plot_paint;
    *(void ***)&screen->plot = screen->plot.vtable;
    screen->items[0] = &screen->plot;

    GuiScrollState_ctor(screen->scroll_state[0]);
    GuiScrollState_ctor(screen->scroll_state[1]);
    GuiTherapyScrollbar_ctor(screen->scrollbar, 12, 12, 0, 6);
    GuiScroller_ctor(screen->scroller, 0, STATISTICS_TOP, 320, STATISTICS_HEIGHT, screen->items, 9, -11,
        (unsigned int)screen->scroll_state[0], (unsigned int)screen->scroll_state[1],
        (unsigned int)screen->scrollbar, 0x40000);
    GuiTreatmentScreen_ctor(screen, root ? (unsigned char *)root + 0x0c : 0,
        root, TEXT_EMPTY, screen->scroller, 10, PAINT_MS);

    vtable = *(void ***)screen;
    for (unsigned int i = 0; i < 21; ++i)
        screen->vtable[i] = vtable[i];
    screen->native_paint = vtable[0x0c / 4];
    screen->vtable[0x0c / 4] = flow_page_paint;
    screen->vtable[0x18 / 4] = flow_page_timer;
    screen->vtable[0x38 / 4] = flow_page_update;
    *(void ***)screen = screen->vtable;

    /* Extend the existing TSS switch: Simple and Pressure retain their native
     * destinations. Flow uses the explicitly reclaimed Reminders page. */
    unsigned char page = (unsigned char)flow_layout.page_index;
    GuiPageAction_ctor(screen->action, &page);
    GuiSwitchAction_add(flow_layout.tss_switch, TSS_FLOW_WAVE, screen->action);
}
