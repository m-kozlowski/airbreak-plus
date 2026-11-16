#ifndef GUI_OBJECTS_H
#define GUI_OBJECTS_H

/* Visitors may remove objects, but must not insert new registry entries. */
void gui_visit_objects(void (*visit)(void *, void *), void *context);

/* Remove window callbacks before deleting the window tree. The caller still
 * owns the C++ objects and their other allocations. */
void gui_destroy_windows(void *root);

#endif
