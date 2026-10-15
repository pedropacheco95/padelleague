# PPL Teams — rules and reference case

Source: Pedro's Teams brief (prompt_claude_code_teams.md) and Estatutos_PPL_Teams.md (2026-10). Decided since: substitutes score nothing; awards stored unrounded, rounded only for display.

## Regras a implementar

### Encontro

- 1 encontro por jornada, 90 minutos, até 3 sets.
- Set ganho = **3 pontos**, empatado = **1**, perdido = **0**.
- Sets a 6 jogos, tie-break a 7, ponto de ouro a 40-40.
- Esgotado o tempo: o set em curso fica **empatado**, e os sets que nem chegaram a
  começar ficam **igualmente empatados**.
- No limite, um encontro em que não se conclua um único set termina com 3 empates e cada
  jogador sai com 3 pontos.
- Invariante para os testes: **todo o encontro produz sempre exatamente 3 resultados de
  set**, cada um `(3,0)`, `(0,3)` ou `(1,1)` entre as duas parelhas. Nunca há encontros
  com menos de 3 resultados registados.
- Só contam os **primeiros 3 sets**. Os jogadores podem continuar a jogar depois disso,
  mas esses sets não são registados.
- O encontro realiza-se sempre que haja substitutos. **Só** quando uma parelha não
  comparece e não consegue qualquer substituto é que o encontro não se joga: aí a parelha
  presente vence por 3 sets a 0 e leva 9 pontos. O walkover é a exceção, não o caminho
  normal para uma falta.

### Pontuação individual

- Os pontos são individuais: ambos os jogadores de uma parelha recebem os pontos dos
  sets que a parelha ganhou ou empatou.
- Um jogador ausente numa jornada recebe **0 pontos** nessa jornada e perde a presença.
  O parceiro presente joga com um substituto externo e **pontua normalmente**, como
  pontuaria na Clássica: a ausência do parceiro não altera em nada o cálculo dos seus
  pontos.
- O substituto não recebe pontos nenhuns e não entra em classificação alguma.

### Classificação do mini-torneio

Individual, dentro de cada divisão, ordenando os 8 jogadores por:

1. Pontos de sets no mini-torneio (desc)
2. Presenças no mini-torneio (desc)

**Nenhum outro critério de desempate.** Os jogadores que fiquem empatados nos dois
critérios ocupam o mesmo lugar, consomem tantas posições quantas forem, e recebem
**todos os pontos de lugar da posição mais alta** do grupo. Exemplo: três empatados a
seguir ao 2.º ocupam as posições 3, 4 e 5, recebem todos os pontos da posição 3, e o
jogador seguinte fica em 6.º.

Isto existe para garantir que dois companheiros de parelha que jogaram exatamente os
mesmos encontros nunca recebam pontuações diferentes.

### Pontos de ranking

Mesma fórmula do sistema atual, com *ratings* próprios da Teams (já representam a
fração de 1/4 por mini-torneio — **não voltes a dividir por 4**):

| Divisão | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|
| rating | 500 | 250 | 125 | 63 | 31 | 16 |

```
pontos de lugar = int(rating * 0.75 ** (posicao - 1))
bonus           = sets_ganhos * rating/100 + sets_empatados * rating/250
pontos          = pontos de lugar + bonus
```

Dois pontos de atenção:

- `sets_ganhos` e `sets_empatados` são **sets**, não encontros. O máximo por
  mini-torneio é 9 sets.
- O **bónus é sempre individual** e não é nivelado pela regra de empate acima: dois
  jogadores na mesma posição recebem os mesmos pontos de lugar mas bónus diferentes se
  tiverem ganho ou empatado sets em número diferente.

Sobre o arredondamento: **vê como o código atual arredonda** a soma lugar + bónus e faz
exatamente igual. Se o código atual não arredondar, não arredondes aqui. Se o fizer,
confirma comigo o modo (`round`, `int`, meio-para-cima) antes de aplicar.

### Formação das parelhas e das divisões

Antes de cada mini-torneio:

1. Cada jogador declara um parceiro. **A escolha só vale se for mútua.**
2. Prazo: domingo à noite anterior à primeira jornada.
3. Quem não tiver parelha mútua ao fim do prazo é emparelhado **por proximidade no
   ranking**: ordena os jogadores sem parelha pela posição no ranking e forma parelhas
   consecutivas — 1.º com 2.º, 3.º com 4.º, e assim por diante. É determinístico, sem
   aleatoriedade. O número de jogadores sem parelha é sempre par, porque as declarações
   mútuas consomem dois de cada vez.
4. **Nenhum jogador pode fazer os 4 mini-torneios com o mesmo parceiro.** Valida isto ao
   fechar os emparelhamentos do 4.º mini-torneio e rejeita a declaração que viole a
   regra.
5. Somam-se os pontos de ranking dos dois jogadores de cada parelha, ordenam-se as 24
   parelhas por esse total, e corta-se em fatias de 4: 1–4 na 1.ª divisão, 5–8 na 2.ª, e
   assim por diante.
6. Empate na soma: fica acima a parelha com o jogador individualmente melhor colocado no
   ranking.

Não há subidas nem descidas. As divisões são refeitas de raiz a cada mini-torneio.

### Assiduidade

Jogador com **3 ou menos jornadas** em 12 é considerado expulso (Art. 11.º do
Regulamento, na mesma proporção). Se já existir lógica de expulsão por assiduidade,
reutiliza-a com este limiar.

## Caso de teste de referência

Divisão 1, um mini-torneio completo. Parelhas A=(P1,P2), B=(P3,P4), C=(P5,P6),
D=(P7,P8).

- **J1:** A–B 3-0 · C–D 1-1 com 1 empate · *P4 ausente*
- **J2:** A–C 2-1 · B–D 1-1 com 1 empate · *P2 ausente*
- **J3:** A–D 1-0 com 2 empates (tempo esgotado) · B–C 3-0

Resultado esperado:

| Pos | Jog | Pts | Pres | V | E | Lugar | Bónus | Total |
|---|---|---|---|---|---|---|---|---|
| 1 | P1 | 20 | 3 | 6 | 2 | 500 | 34 | 534 |
| 2 | P2 | 14 | 2 | 4 | 2 | 375 | 24 | 399 |
| 3 | P3 | 13 | 3 | 4 | 1 | 281 | 22 | 303 |
| 4 | P4 | 13 | 2 | 4 | 1 | 210 | 22 | 232 |
| 5 | P7 | 10 | 3 | 2 | 4 | 158 | 18 | 176 |
| 6 | P8 | 10 | 3 | 2 | 4 | 158 | 18 | 176 |
| 7 | P5 | 7 | 3 | 2 | 1 | 88 | 12 | 100 |
| 8 | P6 | 7 | 3 | 2 | 1 | 88 | 12 | 100 |

Este caso cobre de propósito: o desempate por presenças (P3 vs P4, ambos com 13
pontos), o grupo empatado a consumir duas posições com os mesmos pontos de lugar
(P7/P8 e P5/P6), a ausência a reduzir pontos e presenças (P2), e o encontro terminado
por tempo (J3).

