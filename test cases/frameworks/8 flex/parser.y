%{
extern int yylex(void);
extern int yyerror(char *s);
%}

%token BOOLEAN

%%
input:
  BOOLEAN { $$ = $1;}
;
