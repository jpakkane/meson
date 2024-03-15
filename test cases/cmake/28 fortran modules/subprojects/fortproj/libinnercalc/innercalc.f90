module innercalc
    use collections, only: collection_lookup
    implicit none
    public
    contains
    subroutine do_calculation(number, output)
        integer, intent(in) :: number
        integer, intent(out) :: output
        output = number
        call collection_lookup(number, output)
        output = 2 * (output + 3)
    end subroutine
end module innercalc
