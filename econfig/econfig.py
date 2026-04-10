#!/usr/bin/env python3

# - - - - - - - - - - - - - - - - - - - - - - - -
# econfig.py by ewald@jeitler.cc 2025 https://www.jeitler.guru
# - - - - - - - - - - - - - - - - - - - - - - - -
# When I wrote this code, only god, claude and I knew how it worked.
# Now, only god knows it!
# - - - - - - - - - - - - - - - - - - - - - - - -

version = "0.41" 
import os 
import sys
import re
import ipaddress
import hashlib
import argparse

# - - - - - - - - - - - - - - - - - - - - - - - -
#  the calculation section - depending on the template
# - - - - - - - - - - - - - - - - - - - - - - - -

def calculate_values(inputs,calculated):
    calculated_2 = {}
    if 'wan_link_ip1' in calculated:                         calculated_2['wan_link_ip1'], calculated_2['wan_link_ip2'] = get_host_ips_from_cidr(inputs['wan_network'])
    if 'macsec_key' in calculated:                           calculated_2['macsec_key'] = generiere_macsec_key(calculated_2['wan_link_ip1'] + calculated_2['wan_link_ip2'])
    if 'wan_interface_desc' in calculated:                   calculated_2['wan_interface_desc'] = inputs['wan_interface'].replace("/", "_")
    return calculated_2

def generiere_macsec_key(connection_name):
    ## !!!   CHANGE THIS SALT  !!! ## 
    salt = "SALT_SALT_SALT_SALT_AND_PEPPER_PEPPER_PEPPER"
    key1 = connection_name + "\n"
    key2 = connection_name + salt + "\n"
    res1 = hashlib.md5(key1.encode()).hexdigest()
    res2 = hashlib.md5(key2.encode()).hexdigest()
    return (res1 + res2)

def get_host_ips_from_cidr(cidr_str):
    try:
        network = ipaddress.ip_network(cidr_str +"/30", strict=False)
        hosts = list(network.hosts())
        if len(hosts) != 2:
            raise ValueError("Not a valid /30 network with exactly two usable hosts!")
        return str(hosts[0]), str(hosts[1])
    except ValueError as e:
        print(f"---------------------------------------------------------------")
        print(f"ERROR: {e}")
        print(f"---------------------------------------------------------------")
        return "X.X.X.X", "Y.Y.Y.Y"

# - - - - - - - - - - - - - - - - - - - - - - - -
#   end of calucation section 
# - - - - - - - - - - - - - - - - - - - - - - - -

def get_filename(file_extension):
    result_filelist=[]
    all_files_in_dir = [f.name for f in os.scandir() if f.is_file()]
    for f in all_files_in_dir:
        if f.endswith(file_extension):
            result_filelist.append(f)
    return(result_filelist)

def file_menu(file_extension):
    file_list=get_filename(file_extension)
    # sort filelist 
    file_list=sorted(file_list, key=lambda x: x)
    # print menue 
    print ("--- select template file (.template) ---------------------")
    print ("|  NO | FILENAME ")
    print ("----------------------------------------------------------")
    x = 1
    for list_x in file_list:
        print ('| ' + str(x).rjust(3) + ' |  ' + list_x)
        x=x+1 
    print ("----------------------------------------------------------")
    # get file_number via terminal 
    file_number=input("enter no of file or \"e\" for exit: ")
    while True:
        # exit the menue 
        if file_number == "e" or file_number =="E":
            sys.exit(0)
        # check valid input 
        if file_number.isdigit():
            if int(file_number)<x and int(file_number)>=1:
                break
            else:
                print ("Invalid input. Try again. Range is from 1 to " + str(x-1) +" or e for exit")
                file_number=input("select logfile by number: ") 
        else:
            print ("Invalid input. Try again. Range is from 1 to " + str(x-1) +" or e for exit")
            file_number=input("select logfile by number: ")
    # return selected filename 
    return (file_list[int(file_number)-1])

def parse_user_variables(header_text):
    #    Extract <varname:option1|option2> definitions and return a list of:
    #    (varname, [options]) where options can be empty.
    pattern = r'(?<!<)<([a-zA-Z0-9_\-]+)(?::([^<>]*))?>(?!>)'
    matches = re.findall(pattern, header_text)

    vars_with_options = []
    seen = set()
    for varname, options_str in matches:
        if varname not in seen:
            option_list = options_str.split('|') if options_str else []
            vars_with_options.append((varname, option_list))
            seen.add(varname)
    return vars_with_options

def get_user_inputs(var_list):
    #   Prompt the user for input, showing selectable options if available.
    values = {}
    for varname, options in var_list:
        if options:
            print(f"\nSelect a value for <{varname}>:")
            for idx, option in enumerate(options, start=1):
                print(f"  [{idx}] {option}")
            choice = input("Enter number or type custom value: ").strip()
            if choice.isdigit() and 1 <= int(choice) <= len(options):
                values[varname] = options[int(choice) - 1]
            elif choice:
                values[varname] = choice
            else:
                values[varname] = options[0]  # default to first if empty
        else:
            values[varname] = input(f"Enter value for <{varname}>: ").strip()
    return values


# main def - main def - main def - main def # main def - main def - main def - main def 
# main def - main def - main def - main def # main def - main def - main def - main def 

def replace_variables(filename):
    with open(filename, 'r', encoding='utf-8') as file:
        file_content = file.read()

    separating_line = '!--------end_of_the_variable_definition------------'
    top_part = file_content.split(separating_line)[0]

    # Find <...> variables in sequence
    queried = []
    seen = set()
    for var in re.findall(r'(?<!<)<([a-zA-Z0-9_\-]+)>(?!>)', top_part):
        if var not in seen:
            queried.append(var)
            seen.add(var)

    # Find <...> variables in sequence
    calculated = []
    seen_b = set()
    for var in re.findall(r'<<([a-zA-Z0-9_\-]+)>>', top_part):
        if var not in seen_b:
            calculated.append(var)
            seen_b.add(var)


    # Parse variables
    print(f"\n--- please enter/select values ----------------------------")
    user_var_list = parse_user_variables(top_part)

    user_inputs = get_user_inputs(user_var_list)

    # Generate calculated values
    calculated_values = calculate_values(user_inputs,calculated)
 
    for var in calculated_values:
        file_content = file_content.replace(f'<<{var}>>', calculated_values[var])

    for var in user_inputs:
        file_content = file_content.replace(f'<{var}>', user_inputs[var])

    # output 
    top_part = file_content.split(separating_line)[0]
    config_part = file_content.split(separating_line)[1]

    print(f"\n--- variable definition ----------------------------------")
    print(top_part)
    print (f"--- configuration start ----------------------------------")
    print(config_part)
    print (f"--- configuration end ------------------------------------")

    # save to file 
    if  args.filename_out:
        with open(args.filename_out, 'w', encoding='utf-8') as f_out:
            f_out.write(file_content)
            print("\n--- configuration saved as " + args.filename_out + ".")

if __name__ == "__main__":
    print(f"\n--- econfig.py  " + version + " --- Ewald Jeitler 2025 ---------\n")

    # cli arguement 
    parser = argparse.ArgumentParser()
    # adding optional argument
    parser.add_argument('-t', '--template', default='', dest='filename', help="template filename" )
    parser.add_argument('-o', '--out', default='', dest='filename_out', help="output filename" )
    args = parser.parse_args()

    # start file menu if no args given 
    if not args.filename:
        filename=file_menu("template")
    else:
        filename=args.filename    

    # start main def 
    replace_variables(filename)
    # say thank you
    print ("\nTHX for using econfig.py version " + version + ' - www.jeitler.guru - \n' )