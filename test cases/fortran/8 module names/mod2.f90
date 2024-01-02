module mymod2
use mymod1
implicit none

integer, parameter :: myModVal2 = 2

contains
    subroutine showvalues()
        print*, "myModVal1 = ", myModVal1
        print*, "myModVal2 = ", myModVal2
    end subroutine showvalues


end module mymod2
