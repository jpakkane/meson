module fortproj
    use, intrinsic :: iso_c_binding
    use innercalc, only: do_calculation
    implicit none
    public
    contains
    subroutine layers_of_calculations(input, output) bind(c)
        integer, intent(in) :: input
        integer, intent(out) :: output
        call do_calculation(input, output)
        output = output + 10
    end subroutine
end module
