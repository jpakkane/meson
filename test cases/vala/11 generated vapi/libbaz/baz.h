#include <glib-object.h>

#pragma once

#define BAZ_TYPE_BAZ (baz_baz_get_type())

G_DECLARE_FINAL_TYPE (BazBaz, baz_baz, BAZ, BAZ, GObject)

int baz_baz_return_success(void);
