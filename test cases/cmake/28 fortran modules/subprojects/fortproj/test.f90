program test
    use fortproj, only: layers_of_calculations
    implicit none
    integer :: input, output
    input = 1
    call layers_of_calculations(input, output)
    print*,output
end program
