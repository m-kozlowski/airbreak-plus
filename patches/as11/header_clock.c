/* Local time in the title bar, plus usage minutes during therapy. */

#include "stubs.h"
#include "vars.h"

#define STATUS_STATE_BLINKING 2u
#define MINUTE_MILLISECONDS 60000u

typedef struct {
    unsigned short home;
    unsigned short empty;
    unsigned short menu;
} header_clock_text_ids_t;

/* Native root-widget prefix; the owned-timer callback receives &gui_object. */
typedef struct {
    unsigned char fields_00_0b[0x0c];
    unsigned char gui_object;
    unsigned char fields_0d_67[0x5b];
    unsigned int status_state;
    unsigned char fields_6c_8f[0x24];
    void *status_timer;
} user_interface_root_widget_layout_t;

volatile const header_clock_text_ids_t header_clock_text_ids
    __attribute__((used, section(".rodata.params"))) = {
        0xFFFFu,
        0xFFFFu,
        0xFFFFu,
    };

/* Dashboard, SinglePressure, PressureBar; native page IDs vary by release. */
volatile const unsigned short header_clock_page_ids[3]
    __attribute__((used, section(".rodata.params.pages"))) = {
        0xFFFFu, 0xFFFFu, 0xFFFFu,
    };

/* Replaced with the reclaimed setting ID when custom settings are enabled. */
volatile const unsigned short header_clock_var_id
    __attribute__((used, section(".rodata.params.var_id"))) = 0xFFFFu;

/* The patcher selects the therapy-day (PPD) or mask-interval (PUD) counter. */
volatile const unsigned short header_clock_usage_var_id
    __attribute__((used, section(".rodata.params.usage"))) = VAR_ID_PPD;

static int clock_is_enabled(void)
{
    return header_clock_var_id == 0xFFFFu ||
        DataItem_read_value_by_id(header_clock_var_id) != 0;
}

static int read_local_milliseconds(unsigned int *result)
{
    /* Applies TimeZoneOffset and normalizes day rollover. */
    *result = datetime_current_local_milliseconds_of_day();
    return *result != 0xFFFFFFFFu;
}

static void schedule_next_minute(user_interface_root_widget_layout_t *root)
{
    unsigned int local_ms;
    unsigned int delay = 1000u;

    /* Reuse the root widget's status timer, aligned to the next minute. */
    if (read_local_milliseconds(&local_ms))
        delay = MINUTE_MILLISECONDS - local_ms % MINUTE_MILLISECONDS;
    thunk_gui_timer_handle_reschedule_with_optional_delay(
        root->status_timer, delay);
}

static char *two_digits(char *out, unsigned int value)
{
    *out++ = (char)('0' + value / 10u);
    *out++ = (char)('0' + value % 10u);
    return out;
}

static char *write_hhmm(char *out, unsigned int minutes)
{
    out = two_digits(out, minutes / 60u);
    *out++ = ':';
    return two_digits(out, minutes % 60u);
}

static int format_header(char *text, unsigned int text_id)
{
    unsigned int page = (unsigned int)DataItem_read_value_by_id(VAR_ID_ZMD);
    int therapy = page == header_clock_page_ids[1] || page == header_clock_page_ids[2];
    if (!(therapy && text_id == header_clock_text_ids.empty) &&
        !(page == header_clock_page_ids[0] && text_id == header_clock_text_ids.home))
        return 0;

    char *out = text;
    unsigned int local_ms;
    if (read_local_milliseconds(&local_ms))
        out = write_hhmm(out, local_ms / MINUTE_MILLISECONDS);
    if (therapy) {
        unsigned int minutes = (unsigned int)DataItem_read_value_by_id(header_clock_usage_var_id);
        if (minutes <= 1440u) {
            if (out != text) {
                for (const char *p = "  |  "; *p; ++p)
                    *out++ = *p;
            }
            out = write_hhmm(out, minutes);
        }
    }
    *out = '\0';
    return out != text;
}

void __attribute__((section(".text.0.main")))
start(
    unsigned int text_id,
    void *rect,
    unsigned int text_size,
    unsigned int font,
    int clip,
    unsigned int alignment)
{
    char text[sizeof("HH:MM  |  HH:MM")];

    /* The hook is shared by other title bars; preserve their stock labels. */
    if (!clock_is_enabled() || !format_header(text, text_id)) {
        GuiPaint_DrawLocalizedTextById(
            text_id, rect, text_size, font, clip, alignment);
        return;
    }

    /* Draw dynamic text with the font slot selected for the replaced label. */
    GuiPaint_DrawStringInRect(
        text,
        rect,
        text_size,
        font,
        clip,
        alignment,
        gui_localized_text_font_slot_for_id(text_id));
}

void header_clock_menu_label_draw(
    unsigned int text_id,
    void *rect,
    unsigned int text_size,
    unsigned int font,
    int clip,
    unsigned int alignment)
{
    /* The custom row reuses the detached Reminders text ID. */
    if (header_clock_var_id == 0xFFFFu ||
            text_id != header_clock_text_ids.menu) {
        GuiPaint_DrawLocalizedTextById(
            text_id, rect, text_size, font, clip, alignment);
        return;
    }

    GuiPaint_DrawStringInRect(
        "Clock",
        rect,
        text_size,
        font,
        clip,
        alignment,
        gui_localized_text_font_slot_for_id(text_id));
}

void *header_clock_root_widget_ctor(
    void *root,
    unsigned int arg2,
    unsigned int arg3,
    unsigned int arg4)
{
    /* Preserve construction, then arm its existing timer for clock refresh. */
    user_interface_root_widget_layout_t *layout =
        user_interface_root_widget_ctor(root, arg2, arg3, arg4);

    schedule_next_minute(layout);
    return layout;
}

void header_clock_timer_callback(void *callback_self)
{
    user_interface_root_widget_layout_t *root =
        (user_interface_root_widget_layout_t *)(
            (unsigned char *)callback_self -
            __builtin_offsetof(
                user_interface_root_widget_layout_t, gui_object));

    /* The timer still owns the stock status-blink behavior when it is active. */
    if (root->status_state == STATUS_STATE_BLINKING) {
        user_interface_root_widget_status_blink_timer_callback_adjustor(
            callback_self);
    } else {
        schedule_next_minute(root);
    }

    gui_owned_object_invalidate(&root->gui_object);
}
