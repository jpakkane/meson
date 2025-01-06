%{
#include <stdlib.h>
#include "parser.tab.h"

extern int yylex(void);
extern int yyerror(char *s);
%}

%option noyywrap nounput noinput

%%
("true"|"false")    {return BOOLEAN;}
. { yyerror("Invalid value"); }
