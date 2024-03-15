! This file has a capitalized .F90 file suffix. The only point is to challenge the assumption that
! file suffixes are lowercase. In Fortran projects it's quite common to see a mixture of upper
! and lower case file suffixes. Meson should not care, either.
module collections
    implicit none
    public
    contains
    subroutine collection_lookup(index, output)
        integer, intent(in) :: index
        integer, intent(out) :: output
        if (index == 0) then
            output = 1
        else if (index == 1) then
            output = 3
        else if (index == 2) then
            output = 37
        else if (index == 4) then
            output = 42
        else
            output = 100
        endif
    end subroutine
end module collections
