import array, math

#Dome + Cap calculation -- Lots of math, pretty accurate, or at least I tried
def calculate(H, h, r, b, d, n_theta=50, n_p=50):
    #Dome + Cylinder Cap
    numerator = math.pi * H * (3 * h**2 * H - 2 * h * H**2 + 6 * h * r**2 - 3 * H * r**2 + 6 * h * b**2)
    denominator = 6 * h
    first = numerator / denominator

    #Intersection of dome+cap
    A_sq = ((r**2 + h**2) / (2 * h))**2
    B = (h**2 - r**2) / (2 * h)
    delta_theta = (2 * math.pi) / n_theta
    delta_p = b / n_p
    integral = 0.0
    for i in range(n_theta):
        theta = (i + 0.5) * delta_theta
        cos_theta = math.cos(theta)       
        for j in range(n_p):
            p = (j + 0.5) * delta_p
            sqrt_val = math.sqrt(A_sq - p**2 - d**2 - 2 * p * d * cos_theta)
            term2 = B + sqrt_val
            term_val = min(H, term2)
            integral += term_val * p * delta_p * delta_theta

    return first - integral

domeLookup = array.array('f')
ft = 6.3

# Init the domeLookup to calculate this once per boot
while True:
    ft += .01
    if ft > 7: break # Max height water will reach + couple inches
    domeLookup.append(calculate(H=(ft-6.3)*12, h=13.04, r=47.42, b=11.875, d=35.295, n_theta=50, n_p=50) / 1728) # 1728 Cu in -> Cu ft
print("Done mapping domeLookup")