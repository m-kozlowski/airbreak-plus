#ifndef THERAPY_SCREEN_H
#define THERAPY_SCREEN_H

enum therapy_screen_choice {
    THERAPY_AUTO, THERAPY_SIMPLE, THERAPY_BAR,
    THERAPY_AUTO_GRAPH, THERAPY_SIMPLE_GRAPH, THERAPY_BAR_GRAPH,
    THERAPY_SCREEN_CHOICE_COUNT
};

unsigned therapy_screen_get_choice(void);

static inline int therapy_screen_has_graph(unsigned choice)
{
    return choice == THERAPY_BAR_GRAPH || choice == THERAPY_AUTO_GRAPH ||
           choice == THERAPY_SIMPLE_GRAPH;
}

#endif
