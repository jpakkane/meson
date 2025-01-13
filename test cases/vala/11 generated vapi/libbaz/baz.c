#include "baz.h"
#include <zlib.h>

struct _BazBaz
{
  GObject parent_instance;
};

G_DEFINE_TYPE (BazBaz, baz_baz, G_TYPE_OBJECT)

static void
baz_baz_class_init (BazBazClass *klass)
{
}

static void
baz_baz_init (BazBaz *self)
{
}

/**
 * baz_baz_return_success:
 *
 * Returns 0
 */
int baz_baz_return_zlib_version(void)
{
  return 0;
}
